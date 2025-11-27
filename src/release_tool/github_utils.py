"""GitHub API utilities."""

from datetime import datetime
from typing import List, Dict, Any, Optional
from github import Github, GithubException
from rich.console import Console

from .models import (
    Repository, PullRequest, Ticket, Release, Label
)
from .config import Config

console = Console()


class GitHubClient:
    """GitHub API client wrapper."""

    def __init__(self, config: Config):
        """Initialize GitHub client."""
        self.config = config
        token = config.github.token
        if not token:
            raise ValueError(
                "GitHub token not found. Set GITHUB_TOKEN environment variable "
                "or configure it in release_tool.toml"
            )
        # Set per_page=100 (max) for efficient pagination across all API calls
        self.gh = Github(token, base_url=config.github.api_url, per_page=100)

    def get_repository_info(self, full_name: str) -> Repository:
        """Get repository information."""
        try:
            repo = self.gh.get_repo(full_name)
            owner, name = full_name.split('/')
            return Repository(
                owner=owner,
                name=name,
                full_name=full_name,
                url=repo.html_url,
                default_branch=repo.default_branch
            )
        except GithubException as e:
            raise ValueError(f"Failed to fetch repository {full_name}: {e}")

    def fetch_pull_requests(
        self,
        repo_full_name: str,
        state: str = "closed",
        base_branch: Optional[str] = None
    ) -> List[PullRequest]:
        """Fetch pull requests from GitHub with parallel processing."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from rich.progress import Progress, SpinnerColumn, TextColumn

        try:
            repo = self.gh.get_repo(repo_full_name)

            console.print(f"Fetching pull requests from {repo_full_name}...")

            # First, get PR numbers in batches (this is fast)
            gh_prs = repo.get_pulls(state=state, sort="updated", direction="desc")

            # Process PRs in batches with parallel fetching
            prs_data = []
            batch_size = 100  # Increased for better GitHub API throughput
            processed = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Processing pull requests...", total=None)

                pr_batch = []
                for pr in gh_prs:
                    # Quick filters before parallel processing
                    if base_branch and pr.base.ref != base_branch:
                        continue
                    if not pr.merged_at:
                        continue

                    pr_batch.append(pr)

                    # Process batch when full
                    if len(pr_batch) >= batch_size:
                        batch_results = self._process_pr_batch(pr_batch)
                        prs_data.extend(batch_results)
                        processed += len(pr_batch)

                        progress.update(
                            task,
                            description=f"Processed {processed} pull requests ({len(prs_data)} merged)"
                        )
                        pr_batch = []

                # Process remaining PRs
                if pr_batch:
                    batch_results = self._process_pr_batch(pr_batch)
                    prs_data.extend(batch_results)
                    processed += len(pr_batch)

                    progress.update(
                        task,
                        description=f"Processed {processed} pull requests ({len(prs_data)} merged)"
                    )

            console.print(f"[green]✓[/green] Fetched {len(prs_data)} merged PRs from {processed} candidates")
            return prs_data
        except GithubException as e:
            console.print(f"[red]Error fetching PRs: {e}[/red]")
            return []

    def _process_pr_batch(self, pr_batch: List) -> List[PullRequest]:
        """Process a batch of PRs in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []

        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=20) as executor:
            # Submit all PRs for processing
            future_to_pr = {
                executor.submit(self._pr_to_model, pr, 0): pr
                for pr in pr_batch
            }

            # Collect results as they complete
            for future in as_completed(future_to_pr):
                try:
                    pr_model = future.result()
                    if pr_model:
                        results.append(pr_model)
                except Exception as e:
                    console.print(f"[yellow]Warning: Error processing PR: {e}[/yellow]")

        return results

    def _github_user_to_author(self, gh_user) -> Optional['Author']:
        """Convert PyGithub NamedUser to Author model."""
        from .models import Author

        if not gh_user:
            return None

        try:
            # Use raw_data to avoid lazy loading of fields not in the partial response
            # PyGithub 2.x exposes raw_data
            raw = getattr(gh_user, '_rawData', None)
            if raw is None:
                raw = getattr(gh_user, 'raw_data', {})
            
            return Author(
                username=gh_user.login,
                github_id=gh_user.id,
                name=raw.get('name'),  # Avoid gh_user.name which triggers fetch
                email=raw.get('email'),
                display_name=raw.get('name') or gh_user.login,
                avatar_url=gh_user.avatar_url,
                profile_url=gh_user.html_url,
                company=raw.get('company'),
                location=raw.get('location'),
                bio=raw.get('bio'),
                blog=raw.get('blog'),
                user_type=gh_user.type
            )
        except Exception as e:
            console.print(f"[yellow]Warning: Error creating author from GitHub user: {e}[/yellow]")
            # Return minimal author with just username
            return Author(username=gh_user.login if hasattr(gh_user, 'login') else None)

    def _pr_to_model(self, gh_pr, repo_id: int) -> PullRequest:
        """Convert PyGithub PR to our model, avoiding lazy loads."""
        # Use internal _rawData if available to avoid any property overhead or lazy loading checks
        raw = getattr(gh_pr, '_rawData', None)
        if raw is None:
             raw = getattr(gh_pr, 'raw_data', {})

        # Extract labels from raw data to avoid lazy load
        labels = []
        for label_data in raw.get('labels', []):
            labels.append(Label(
                name=label_data.get('name', ''),
                color=label_data.get('color', ''),
                description=label_data.get('description')
            ))

        # Extract base/head branches from raw data to avoid lazy load
        base_data = raw.get('base', {})
        head_data = raw.get('head', {})

        # Get user data from raw to avoid lazy load
        user_data = raw.get('user')
        # Create a mock object with raw_data for _github_user_to_author
        from types import SimpleNamespace
        gh_user = None
        if user_data:
            gh_user = SimpleNamespace(
                login=user_data.get('login'),
                id=user_data.get('id'),
                avatar_url=user_data.get('avatar_url'),
                html_url=user_data.get('html_url'),
                type=user_data.get('type'),
                raw_data=user_data
            )

        return PullRequest(
            repo_id=repo_id,
            number=raw.get('number'),
            title=raw.get('title'),
            body=raw.get('body'),
            state=raw.get('state'),
            merged_at=raw.get('merged_at'),
            author=self._github_user_to_author(gh_user),
            base_branch=base_data.get('ref'),
            head_branch=head_data.get('ref'),
            head_sha=head_data.get('sha'),
            labels=labels,
            url=raw.get('html_url')
        )

    def _issue_to_ticket(self, gh_issue, repo_id: int) -> Ticket:
        """Convert PyGithub Issue to our Ticket model, avoiding lazy loads."""
        # Use internal _rawData if available to avoid any property overhead or lazy loading checks
        # PyGithub stores the raw dictionary in _rawData
        raw = getattr(gh_issue, '_rawData', None)
        if raw is None:
             # Fallback to public raw_data
             raw = getattr(gh_issue, 'raw_data', {})
        
        # Extract labels from raw data to avoid lazy load
        labels = []
        for label_data in raw.get('labels', []):
            labels.append(Label(
                name=label_data.get('name', ''),
                color=label_data.get('color', ''),
                description=label_data.get('description')
            ))
            
        # Get number from raw_data to be absolutely sure we avoid any lazy loads
        number = raw.get('number')
        if number is None:
             # Only access gh_issue.number if absolutely necessary (fallback)
             number = gh_issue.number
             
        ticket = Ticket(
            repo_id=repo_id,
            number=number,
            key=str(number),
            title=raw.get('title'),
            body=raw.get('body'),
            state=raw.get('state'),
            labels=labels,
            url=raw.get('html_url'),
            created_at=raw.get('created_at'),
            closed_at=raw.get('closed_at')
        )
        
        return ticket

    def fetch_issue(self, repo_full_name: str, issue_number: int, repo_id: int) -> Optional[Ticket]:
        """Fetch a single issue/ticket from GitHub."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)

            labels = [
                Label(name=label.name, color=label.color, description=label.description)
                for label in issue.labels
            ]

            return Ticket(
                repo_id=repo_id,
                number=issue.number,
                key=str(issue.number),
                title=issue.title,
                body=issue.body,
                state=issue.state,
                labels=labels,
                url=issue.html_url,
                created_at=issue.created_at,
                closed_at=issue.closed_at
            )
        except GithubException as e:
            console.print(f"[yellow]Warning: Could not fetch issue #{issue_number}: {e}[/yellow]")
            return None

    def fetch_issue_by_key(
        self,
        repo_full_name: str,
        ticket_key: str,
        repo_id: int
    ) -> Optional[Ticket]:
        """Fetch issue by ticket key (e.g., '#123' or 'PROJ-123')."""
        # Extract number from key
        import re
        match = re.search(r'(\d+)', ticket_key)
        if not match:
            return None

        issue_number = int(match.group(1))
        return self.fetch_issue(repo_full_name, issue_number, repo_id)

    def search_issue_numbers(
        self,
        repo_full_name: str,
        since: Optional[datetime] = None
    ) -> List[int]:
        """
        Get issue numbers using Core API with explicit pagination.

        Uses GET /repos/{owner}/{repo}/issues endpoint with per_page=100.
        Manually paginates to ensure we fetch 100 items per request.

        IMPORTANT: This endpoint returns both issues AND pull requests (PRs are issues in GitHub API).
        Returns all numbers - filtering happens downstream if needed.

        Core API limit: 5000 req/hour (much higher than Search API's 30 req/min).

        Args:
            repo_full_name: Full repository name (owner/repo)
            since: Only include issues created after this datetime

        Returns:
            List of issue numbers (includes both issues and PRs)
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn

        try:
            repo = self.gh.get_repo(repo_full_name)

            # Use Core API with explicit pagination
            # state='all' to get both open and closed
            # Note: This returns both issues AND pull requests
            issues_paginated = repo.get_issues(
                state='all',
                since=since,
                sort='created',
                direction='asc'
            )

            issue_numbers = []
            page_num = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Fetching issues...", total=None)

                # Explicitly paginate through results to fetch 100 at a time
                while True:
                    try:
                        # Get page (PyGithub caches pages internally)
                        page = issues_paginated.get_page(page_num)

                        if not page:
                            break

                        # Process the page (100 items) - just get the numbers
                        # Note: This includes both issues AND PRs (PRs are issues in GitHub API)
                        for issue in page:
                            issue_numbers.append(issue.number)

                        page_num += 1
                        progress.update(task, description=f"Fetching issues... {len(issue_numbers)} found (page {page_num})")

                    except Exception as e:
                        # No more pages
                        break

            console.print(f"  [green]✓[/green] Found {len(issue_numbers)} issues")
            return issue_numbers

        except GithubException as e:
            console.print(f"[red]Error fetching issues from {repo_full_name}: {e}[/red]")
            return []

    def search_ticket_numbers(self, repo_full_name: str, since: Optional[datetime] = None) -> List[int]:
        """Deprecated: Use search_issue_numbers() instead."""
        return self.search_issue_numbers(repo_full_name, since)

    def fetch_all_issues(
        self,
        repo_full_name: str,
        repo_id: int,
        since: Optional[datetime] = None
    ) -> List[Ticket]:
        """
        Fetch all issues as Ticket objects using Core API with efficient pagination.

        Uses GET /repos/{owner}/{repo}/issues endpoint with per_page=100.
        Fetches full issue data and converts to Ticket objects in one pass.

        IMPORTANT: GitHub's /issues endpoint returns both issues AND pull requests.
        PRs are filtered out by checking if pull_request field is None.

        Core API limit: 5000 req/hour.

        Args:
            repo_full_name: Full repository name (owner/repo)
            repo_id: Repository ID in database
            since: Only include issues created after this datetime

        Returns:
            List of Ticket objects (PRs excluded)
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn
        import time

        try:
            repo = self.gh.get_repo(repo_full_name)

            # Use Core API with explicit pagination
            issues_paginated = repo.get_issues(
                state='all',
                since=since,
                sort='created',
                direction='asc'
            )

            tickets = []
            page_num = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Fetching issues...", total=None)

                # Explicitly paginate through results to fetch 100 at a time
                while True:
                    try:
                        page_start = time.time()
                        progress.update(task, description=f"Fetching issues... page {page_num + 1} (fetching...)")

                        # Get page (100 items) - force to list to avoid lazy iteration
                        page = issues_paginated.get_page(page_num)

                        if not page:
                            break

                        # Force page to list to ensure all data is loaded
                        page = list(page)

                        page_fetch_time = time.time() - page_start
                        progress.update(task, description=f"Fetching issues... page {page_num + 1} ({len(page)} items in {page_fetch_time:.1f}s, converting...)")

                        # Convert issues to Ticket objects directly
                        convert_start = time.time()
                        for idx, issue in enumerate(page):
                            item_start = time.time()
                            # Convert to Ticket using helper (doesn't trigger extra API calls)
                            ticket = self._issue_to_ticket(issue, repo_id)
                            tickets.append(ticket)
                            item_time = time.time() - item_start

                            # Update every 10 items to show progress
                            if (idx + 1) % 10 == 0:
                                avg_time = (time.time() - convert_start) / (idx + 1)
                                progress.update(task, description=f"Fetching issues... page {page_num + 1} (converting {idx + 1}/{len(page)}... {avg_time*1000:.0f}ms/item)")

                        convert_time = time.time() - convert_start
                        page_num += 1
                        progress.update(task, description=f"Fetching issues... {len(tickets)} found (page {page_num} done in {page_fetch_time + convert_time:.1f}s)")

                    except Exception as e:
                        # No more pages
                        break

            console.print(f"  [green]✓[/green] Found {len(tickets)} issues")
            return tickets

        except GithubException as e:
            console.print(f"[red]Error fetching issues from {repo_full_name}: {e}[/red]")
            return []

    def search_tickets(
        self,
        repo_full_name: str,
        repo_id: int,
        since: Optional[datetime] = None
    ) -> List[Ticket]:
        """
        Search for tickets using GitHub Search API and return full Ticket objects.

        This is more efficient than search_ticket_numbers() + fetch_issue() for each,
        as it extracts all ticket data directly from search results without additional API calls.

        GitHub Search API has a 1000-result limit per query. This method handles
        that by chunking the date range when needed.

        Args:
            repo_full_name: Full repository name (owner/repo)
            repo_id: Repository ID in database
            since: Only include tickets created after this datetime

        Returns:
            List of Ticket objects with full data
        """
        from datetime import timedelta

        try:
            console.print(f"  [cyan]Searching for tickets...[/cyan]")

            # NOTE: GitHub Search API has a 1000-result limit per query
            # AND it lies about totalCount - it caps at 1000 even when there are more results
            # So we must always chunk and check if we hit exactly 1000 results

            tickets = []
            current_start = since

            while True:
                # Query for this chunk (sorted ascending to get oldest first in this range)
                chunk_query = f"repo:{repo_full_name} is:issue"
                if current_start:
                    chunk_query += f" created:>={current_start.strftime('%Y-%m-%d')}"

                chunk_issues = self.gh.search_issues(chunk_query, sort='created', order='asc')
                chunk_count = chunk_issues.totalCount

                if chunk_count == 0:
                    break

                # Show progress
                if len(tickets) == 0:
                    if chunk_count >= 1000:
                        console.print(f"  [yellow]Note: API shows {chunk_count} tickets, but there may be more (API limit: 1000)[/yellow]")
                    else:
                        console.print(f"  [dim]Total tickets to fetch: {chunk_count}[/dim]")

                # Fetch up to 1000 from this chunk
                fetched_in_chunk = 0
                last_created_date = None

                for issue in chunk_issues:
                    # Convert to Ticket object directly (no additional API call needed!)
                    ticket = self._issue_to_ticket(issue, repo_id)
                    tickets.append(ticket)
                    last_created_date = issue.created_at
                    fetched_in_chunk += 1

                    if len(tickets) % 100 == 0:
                        console.print(f"  [dim]Found {len(tickets)} tickets...[/dim]")

                    # Stop at 1000 per chunk to avoid API limit
                    if fetched_in_chunk >= 1000:
                        break

                # If we fetched less than 1000, we're done (no more results)
                if fetched_in_chunk < 1000:
                    break

                # We fetched exactly 1000 - there might be more, continue to next chunk
                if last_created_date:
                    current_start = last_created_date + timedelta(seconds=1)
                    console.print(f"  [yellow]Fetched 1000 results - chunking to continue from {current_start.strftime('%Y-%m-%d %H:%M:%S')}...[/yellow]")
                else:
                    break

            console.print(f"  [green]✓[/green] Found {len(tickets)} tickets with full data")
            return tickets

        except GithubException as e:
            console.print(f"[red]Error searching tickets from {repo_full_name}: {e}[/red]")
            return []

    def search_pr_numbers(
        self,
        repo_full_name: str,
        since: Optional[datetime] = None
    ) -> List[int]:
        """
        Get merged PR numbers using Core API with explicit pagination.

        Uses GET /repos/{owner}/{repo}/pulls endpoint with per_page=100.
        Manually paginates to ensure we fetch 100 items per request.

        Core API limit: 5000 req/hour (much higher than Search API's 30 req/min).

        Args:
            repo_full_name: Full repository name (owner/repo)
            since: Only include PRs merged after this datetime

        Returns:
            List of PR numbers
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn

        try:
            repo = self.gh.get_repo(repo_full_name)

            # Use Core API with explicit pagination
            # state='closed' gets both merged and closed-without-merge
            prs_paginated = repo.get_pulls(
                state='closed',
                sort='created',
                direction='asc'
            )

            pr_numbers = []
            page_num = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Fetching PRs...", total=None)

                # Explicitly paginate through results to fetch 100 at a time
                while True:
                    try:
                        # Get page (PyGithub caches pages internally)
                        page = prs_paginated.get_page(page_num)

                        if not page:
                            break

                        # Process the page (100 items)
                        for pr in page:
                            # Filter to only merged PRs and respect since date
                            if pr.merged_at:
                                if since is None or pr.merged_at >= since:
                                    pr_numbers.append(pr.number)

                        page_num += 1
                        progress.update(task, description=f"Fetching PRs... {len(pr_numbers)} found (page {page_num})")

                    except Exception as e:
                        # No more pages
                        break

            console.print(f"  [green]✓[/green] Found {len(pr_numbers)} merged PRs")
            return pr_numbers

        except GithubException as e:
            console.print(f"[red]Error fetching PRs from {repo_full_name}: {e}[/red]")
            return []

    def fetch_all_pull_requests(
        self,
        repo_full_name: str,
        repo_id: int,
        since: Optional[datetime] = None
    ) -> List[PullRequest]:
        """
        Fetch all PRs as PullRequest objects using Core API with efficient pagination.

        Uses GET /repos/{owner}/{repo}/pulls endpoint with per_page=100.
        Fetches full PR data and converts to PullRequest objects in one pass.

        Note: Gets all closed PRs. Filtering (merged vs closed, since date) happens downstream.

        Core API limit: 5000 req/hour.

        Args:
            repo_full_name: Full repository name (owner/repo)
            repo_id: Repository ID in database
            since: Only include PRs created after this datetime (filtering done downstream)

        Returns:
            List of PullRequest objects (all closed PRs)
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn
        import time

        try:
            repo = self.gh.get_repo(repo_full_name)

            # Use Core API with explicit pagination
            # state='closed' gets both merged and closed-without-merge
            prs_paginated = repo.get_pulls(
                state='closed',
                sort='created',
                direction='asc'
            )

            pull_requests = []
            page_num = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Fetching PRs...", total=None)

                # Explicitly paginate through results to fetch 100 at a time
                while True:
                    try:
                        page_start = time.time()
                        progress.update(task, description=f"Fetching PRs... page {page_num + 1} (fetching...)")

                        # Get page (100 items) - force to list to avoid lazy iteration
                        page = prs_paginated.get_page(page_num)

                        if not page:
                            break

                        # Force page to list to ensure all data is loaded
                        page = list(page)

                        page_fetch_time = time.time() - page_start
                        progress.update(task, description=f"Fetching PRs... page {page_num + 1} ({len(page)} items in {page_fetch_time:.1f}s, converting...)")

                        # Convert all PRs to PullRequest objects directly (no filtering here)
                        convert_start = time.time()
                        for idx, pr in enumerate(page):
                            item_start = time.time()
                            pr_obj = self._pr_to_model(pr, repo_id)
                            pull_requests.append(pr_obj)
                            item_time = time.time() - item_start

                            # Update every 10 items to show progress
                            if (idx + 1) % 10 == 0:
                                avg_time = (time.time() - convert_start) / (idx + 1)
                                progress.update(task, description=f"Fetching PRs... page {page_num + 1} (converting {idx + 1}/{len(page)}... {avg_time*1000:.0f}ms/item)")

                        convert_time = time.time() - convert_start
                        page_num += 1
                        progress.update(task, description=f"Fetching PRs... {len(pull_requests)} found (page {page_num} done in {page_fetch_time + convert_time:.1f}s)")

                    except Exception as e:
                        # No more pages
                        break

            console.print(f"  [green]✓[/green] Found {len(pull_requests)} PRs")
            return pull_requests

        except GithubException as e:
            console.print(f"[red]Error fetching PRs from {repo_full_name}: {e}[/red]")
            return []

    def search_pull_requests(
        self,
        repo_full_name: str,
        repo_id: int,
        since: Optional[datetime] = None
    ) -> List[PullRequest]:
        """
        Search for merged PRs using GitHub Search API and return full PullRequest objects.

        This is more efficient than search_pr_numbers() + get_pull_request() for each,
        as it extracts all PR data directly from search results without additional API calls.

        GitHub Search API has a 1000-result limit per query. This method handles
        that by chunking the date range when needed.

        Args:
            repo_full_name: Full repository name (owner/repo)
            repo_id: Repository ID in database
            since: Only include PRs merged after this datetime

        Returns:
            List of PullRequest objects with full data
        """
        from datetime import timedelta

        try:
            console.print(f"  [cyan]Searching for merged PRs...[/cyan]")

            # NOTE: GitHub Search API has a 1000-result limit per query
            # AND it lies about totalCount - it caps at 1000 even when there are more results
            # So we must always chunk and check if we hit exactly 1000 results

            prs = []
            current_start = since

            while True:
                # Query for this chunk (sorted ascending to get oldest first in this range)
                chunk_query = f"repo:{repo_full_name} is:pr is:merged"
                if current_start:
                    chunk_query += f" merged:>={current_start.strftime('%Y-%m-%d')}"

                chunk_prs = self.gh.search_issues(chunk_query, sort='created', order='asc')
                chunk_count = chunk_prs.totalCount

                if chunk_count == 0:
                    break

                # Show progress
                if len(prs) == 0:
                    if chunk_count >= 1000:
                        console.print(f"  [yellow]Note: API shows {chunk_count} PRs, but there may be more (API limit: 1000)[/yellow]")
                    else:
                        console.print(f"  [dim]Total PRs to fetch: {chunk_count}[/dim]")

                # Fetch up to 1000 from this chunk
                fetched_in_chunk = 0
                last_created_date = None

                for pr in chunk_prs:
                    # Convert to PullRequest object directly (no additional API call needed!)
                    pr_obj = self._pr_to_model(pr, repo_id)
                    prs.append(pr_obj)
                    last_created_date = pr.created_at
                    fetched_in_chunk += 1

                    if len(prs) % 500 == 0:
                        console.print(f"  [dim]Found {len(prs)} merged PRs...[/dim]")

                    # Stop at 1000 per chunk to avoid API limit
                    if fetched_in_chunk >= 1000:
                        break

                # If we fetched less than 1000, we're done (no more results)
                if fetched_in_chunk < 1000:
                    break

                # We fetched exactly 1000 - there might be more, continue to next chunk
                if last_created_date:
                    current_start = last_created_date + timedelta(seconds=1)
                    console.print(f"  [yellow]Fetched 1000 results - chunking to continue from {current_start.strftime('%Y-%m-%d %H:%M:%S')}...[/yellow]")
                else:
                    break

            console.print(f"  [green]✓[/green] Found {len(prs)} merged PRs with full data")
            return prs

        except GithubException as e:
            console.print(f"[red]Error searching PRs from {repo_full_name}: {e}[/red]")
            return []

    def get_ticket(
        self,
        repo_full_name: str,
        ticket_number: int
    ) -> Optional[Ticket]:
        """
        Get a single ticket (convenience method for parallel fetching).

        Args:
            repo_full_name: Full repository name (owner/repo)
            ticket_number: Ticket number

        Returns:
            Ticket model or None
        """
        # Need to get repo_id first
        repo_info = self.get_repository_info(repo_full_name)
        # Assuming repo_id is stored - we'll need to look it up from DB
        # For now, use a temporary value and let the caller handle it
        return self.fetch_issue(repo_full_name, ticket_number, repo_id=0)

    def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int
    ) -> Optional[PullRequest]:
        """
        Get a single pull request (convenience method for parallel fetching).

        Args:
            repo_full_name: Full repository name (owner/repo)
            pr_number: PR number

        Returns:
            PullRequest model or None
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            gh_pr = repo.get_pull(pr_number)

            # Need repo_id - use 0 for now and let caller handle it
            return self._pr_to_model(gh_pr, repo_id=0)
        except GithubException as e:
            console.print(f"[yellow]Warning: Could not fetch PR #{pr_number}: {e}[/yellow]")
            return None

    def fetch_releases(self, repo_full_name: str, repo_id: int) -> List[Release]:
        """Fetch releases from GitHub with parallel processing."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            repo = self.gh.get_repo(repo_full_name)
            releases = []

            # Get all release objects first (lightweight)
            gh_releases = list(repo.get_releases())

            if not gh_releases:
                return []

            # Process releases in parallel
            def process_release(gh_release):
                try:
                    return Release(
                        repo_id=repo_id,
                        version=gh_release.tag_name.lstrip('v'),
                        tag_name=gh_release.tag_name,
                        name=gh_release.title,
                        body=gh_release.body,
                        created_at=gh_release.created_at,
                        published_at=gh_release.published_at,
                        is_draft=gh_release.draft,
                        is_prerelease=gh_release.prerelease,
                        url=gh_release.html_url
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Error processing release: {e}[/yellow]")
                    return None

            with ThreadPoolExecutor(max_workers=20) as executor:
                future_to_release = {
                    executor.submit(process_release, gh_release): gh_release
                    for gh_release in gh_releases
                }

                for future in as_completed(future_to_release):
                    release = future.result()
                    if release:
                        releases.append(release)

            return releases
        except GithubException as e:
            console.print(f"[yellow]Warning: Could not fetch releases: {e}[/yellow]")
            return []

    def create_release(
        self,
        repo_full_name: str,
        version: str,
        name: str,
        body: str,
        draft: bool = False,
        prerelease: bool = False
    ) -> Optional[str]:
        """Create a GitHub release."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            tag_name = f"{self.config.version_policy.tag_prefix}{version}"

            release = repo.create_git_release(
                tag=tag_name,
                name=name,
                message=body,
                draft=draft,
                prerelease=prerelease
            )

            console.print(f"[green]Created release: {release.html_url}[/green]")
            return release.html_url
        except GithubException as e:
            console.print(f"[red]Error creating release: {e}[/red]")
            return None

    def create_pr_for_release_notes(
        self,
        repo_full_name: str,
        pr_title: str,
        file_path: str,
        content: str,
        branch_name: str,
        target_branch: str,
        pr_body: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a PR with release notes.

        Args:
            repo_full_name: Full repository name (owner/repo)
            pr_title: Title for the pull request
            file_path: Path to the release notes file in the repo
            content: Content of the release notes file
            branch_name: Name of the branch to create
            target_branch: Target branch for the PR (e.g., main)
            pr_body: Optional body text for the PR

        Returns:
            URL of the created PR or None if failed
        """
        try:
            repo = self.gh.get_repo(repo_full_name)

            # Get base branch reference
            base_ref = repo.get_git_ref(f"heads/{target_branch}")
            base_sha = base_ref.object.sha

            # Create new branch
            try:
                repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)
            except GithubException:
                # Branch might already exist
                pass

            # Determine commit message from pr_title
            commit_msg = f"Update {file_path}"

            # Get or create the file
            try:
                file_contents = repo.get_contents(file_path, ref=branch_name)
                # Update existing file
                repo.update_file(
                    file_path,
                    commit_msg,
                    content,
                    file_contents.sha,
                    branch=branch_name
                )
            except GithubException:
                # Create new file
                repo.create_file(
                    file_path,
                    commit_msg,
                    content,
                    branch=branch_name
                )

            # Create PR with custom title and body
            pr_body_text = pr_body if pr_body else f"Automated release notes update"
            pr = repo.create_pull(
                title=pr_title,
                body=pr_body_text,
                head=branch_name,
                base=target_branch
            )

            console.print(f"[green]Created PR: {pr.html_url}[/green]")
            return pr.html_url
        except GithubException as e:
            console.print(f"[red]Error creating PR: {e}[/red]")
            return None
