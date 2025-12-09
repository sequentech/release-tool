# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""GitHub API utilities."""

from datetime import datetime
from typing import List, Dict, Any, Optional
from github import Github, GithubException
from rich.console import Console

from .models import (
    Repository, PullRequest, Issue, Release, Label
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

    def _issue_to_issue(self, gh_issue, repo_id: int) -> Issue:
        """Convert PyGithub Issue to our Issue model, avoiding lazy loads."""
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
             
        issue = Issue(
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
        
        return issue

    def fetch_issue(self, repo_full_name: str, issue_number: int, repo_id: int) -> Optional[Issue]:
        """Fetch a single issue/issue from GitHub."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)

            labels = [
                Label(name=label.name, color=label.color, description=label.description)
                for label in issue.labels
            ]

            return Issue(
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
        issue_key: str,
        repo_id: int
    ) -> Optional[Issue]:
        """Fetch issue by issue key (e.g., '#123' or 'PROJ-123')."""
        # Extract number from key
        import re
        match = re.search(r'(\d+)', issue_key)
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

                # Explicitly paginates through results to fetch 100 at a time
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

    def search_issue_numbers(self, repo_full_name: str, since: Optional[datetime] = None) -> List[int]:
        """Deprecated: Use search_issue_numbers() instead."""
        return self.search_issue_numbers(repo_full_name, since)

    def fetch_all_issues(
        self,
        repo_full_name: str,
        repo_id: int,
        since: Optional[datetime] = None
    ) -> List[Issue]:
        """
        Fetch all issues as Issue objects using Core API with efficient pagination.

        Uses GET /repos/{owner}/{repo}/issues endpoint with per_page=100.
        Fetches full issue data and converts to Issue objects in one pass.

        IMPORTANT: GitHub's /issues endpoint returns both issues AND pull requests.
        PRs are filtered out by checking if pull_request field is None.

        Core API limit: 5000 req/hour.

        Args:
            repo_full_name: Full repository name (owner/repo)
            repo_id: Repository ID in database
            since: Only include issues created after this datetime

        Returns:
            List of Issue objects (PRs excluded)
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn
        import time

        try:
            repo = self.gh.get_repo(repo_full_name)

            # Use Core API with explicit pagination
            # Build kwargs conditionally - PyGithub doesn't accept since=None
            kwargs = {
                'state': 'all',
                'sort': 'created',
                'direction': 'asc'
            }
            if since is not None:
                kwargs['since'] = since
            
            issues_paginated = repo.get_issues(**kwargs)

            issues = []
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

                        # Convert issues to Issue objects directly
                        convert_start = time.time()
                        for idx, gh_item in enumerate(page):
                            # Skip PRs - GitHub's /issues endpoint returns both issues and PRs
                            # Check raw_data to avoid lazy loading
                            raw = getattr(gh_item, '_rawData', None) or getattr(gh_item, 'raw_data', {})
                            if raw.get('pull_request') is not None:
                                continue
                            
                            item_start = time.time()
                            # Convert to Issue using helper (doesn't trigger extra API calls)
                            issue_obj = self._issue_to_issue(gh_item, repo_id)
                            issues.append(issue_obj)
                            item_time = time.time() - item_start

                            # Update every 10 items to show progress
                            if len(issues) % 10 == 0:
                                avg_time = (time.time() - convert_start) / len(issues)
                                progress.update(task, description=f"Fetching issues... page {page_num + 1} (converting {len(issues)} issues... {avg_time*1000:.0f}ms/item)")

                        convert_time = time.time() - convert_start
                        page_num += 1
                        progress.update(task, description=f"Fetching issues... {len(issues)} found (page {page_num} done in {page_fetch_time + convert_time:.1f}s)")

                    except Exception as e:
                        # No more pages
                        break

            console.print(f"  [green]✓[/green] Found {len(issues)} issues")
            return issues

        except GithubException as e:
            console.print(f"[red]Error fetching issues from {repo_full_name}: {e}[/red]")
            return []

    def search_issues(
        self,
        repo_full_name: str,
        repo_id: int,
        since: Optional[datetime] = None
    ) -> List[Issue]:
        """
        Search for issues using GitHub Search API and return full Issue objects.

        This is more efficient than search_issue_numbers() + fetch_issue() for each,
        as it extracts all issue data directly from search results without additional API calls.

        GitHub Search API has a 1000-result limit per query. This method handles
        that by chunking the date range when needed.

        Args:
            repo_full_name: Full repository name (owner/repo)
            repo_id: Repository ID in database
            since: Only include issues created after this datetime

        Returns:
            List of Issue objects with full data
        """
        from datetime import timedelta

        try:
            console.print(f"  [cyan]Searching for issues...[/cyan]")

            # NOTE: GitHub Search API has a 1000-result limit per query
            # AND it lies about totalCount - it caps at 1000 even when there are more results
            # So we must always chunk and check if we hit exactly 1000 results

            issues = []
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
                if len(issues) == 0:
                    if chunk_count >= 1000:
                        console.print(f"  [yellow]Note: API shows {chunk_count} issues, but there may be more (API limit: 1000)[/yellow]")
                    else:
                        console.print(f"  [dim]Total issues to fetch: {chunk_count}[/dim]")

                # Fetch up to 1000 from this chunk
                fetched_in_chunk = 0
                last_created_date = None

                for issue in chunk_issues:
                    # Convert to Issue object directly (no additional API call needed!)
                    issue = self._issue_to_issue(issue, repo_id)
                    issues.append(issue)
                    last_created_date = issue.created_at
                    fetched_in_chunk += 1

                    if len(issues) % 100 == 0:
                        console.print(f"  [dim]Found {len(issues)} issues...[/dim]")

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

            console.print(f"  [green]✓[/green] Found {len(issues)} issues with full data")
            return issues

        except GithubException as e:
            console.print(f"[red]Error searching issues from {repo_full_name}: {e}[/red]")
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

    def get_issue(
        self,
        repo_full_name: str,
        issue_number: int
    ) -> Optional[Issue]:
        """
        Get a single issue (convenience method for parallel fetching).

        Args:
            repo_full_name: Full repository name (owner/repo)
            issue_number: Issue number

        Returns:
            Issue model or None
        """
        # Need to get repo_id first
        repo_info = self.get_repository_info(repo_full_name)
        # Assuming repo_id is stored - we'll need to look it up from DB
        # For now, use a temporary value and let the caller handle it
        return self.fetch_issue(repo_full_name, issue_number, repo_id=0)

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

    def get_release_by_tag(
        self,
        repo_full_name: str,
        tag_name: str
    ) -> Optional[Any]:
        """Get a GitHub release by tag name.
        
        Searches for releases in two ways:
        1. Direct lookup by tag name
        2. Search all releases for matching tag_name (handles "untagged" releases)
        
        Args:
            repo_full_name: Repository in "owner/repo" format
            tag_name: Tag name (e.g., "v1.0.0")
            
        Returns:
            GitHub release object if found, None otherwise
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            
            # First try direct lookup by tag
            try:
                release = repo.get_release(tag_name)
                return release
            except GithubException:
                pass
            
            # If direct lookup fails, search through all releases
            # This handles "untagged" releases that may have the tag in their name
            releases = repo.get_releases()
            for release in releases:
                # Check if the release's tag_name matches (even for untagged)
                if release.tag_name == tag_name:
                    return release
                # Also check if this is an untagged release with our version in the name
                if release.tag_name.startswith("untagged-") and tag_name in release.title:
                    return release
            
            return None
        except GithubException:
            # Repository not found or other error
            return None

    def update_release(
        self,
        repo_full_name: str,
        tag_name: str,
        name: Optional[str] = None,
        body: Optional[str] = None,
        draft: Optional[bool] = None,
        prerelease: Optional[bool] = None,
        target_commitish: Optional[str] = None
    ) -> Optional[str]:
        """Update an existing GitHub release.
        
        If the release is "untagged", it will be deleted and recreated with the proper tag,
        since GitHub doesn't properly update untagged releases to tagged ones.
        
        Args:
            repo_full_name: Repository in "owner/repo" format
            tag_name: Tag name of the release to update
            name: New release name (optional)
            body: New release body (optional)
            draft: New draft status (optional)
            prerelease: New prerelease status (optional)
            target_commitish: New target commitish (optional)
            
        Returns:
            Release URL if successful, None otherwise
        """
        try:
            release = self.get_release_by_tag(repo_full_name, tag_name)
            if not release:
                console.print(f"[red]Error: Release with tag {tag_name} not found[/red]")
                return None

            # Check if this is an untagged release
            is_untagged = release.tag_name.startswith("untagged-")
            
            if is_untagged:
                # Delete the untagged release and recreate it properly
                console.print(f"[yellow]Detected untagged release, deleting and recreating with proper tag...[/yellow]")
                try:
                    release.delete_release()
                    console.print(f"[dim]✓ Deleted untagged release[/dim]")
                except GithubException as e:
                    console.print(f"[red]Error deleting untagged release: {e}[/red]")
                    return None
                
                # Extract version from tag_name (remove 'v' prefix if present)
                version = tag_name.lstrip('v')
                
                # Create new release with proper tag
                return self.create_release(
                    repo_full_name=repo_full_name,
                    version=version,
                    name=name or release.title,
                    body=body or release.body,
                    draft=draft if draft is not None else release.draft,
                    prerelease=prerelease if prerelease is not None else release.prerelease,
                    target_commitish=target_commitish or release.target_commitish
                )

            # Try to update the release - wrap in try/except to catch deleted releases
            try:
                # Update only provided fields
                if name is not None:
                    release.update_release(name=name, message=body or release.body, 
                                          draft=draft if draft is not None else release.draft,
                                          prerelease=prerelease if prerelease is not None else release.prerelease,
                                          tag_name=tag_name,
                                          target_commitish=target_commitish or release.target_commitish)
                elif body is not None or draft is not None or prerelease is not None or target_commitish is not None:
                    release.update_release(name=release.title, 
                                          message=body if body is not None else release.body,
                                          draft=draft if draft is not None else release.draft,
                                          prerelease=prerelease if prerelease is not None else release.prerelease,
                                          tag_name=tag_name,
                                          target_commitish=target_commitish or release.target_commitish)
            except GithubException as e:
                # Release might have been deleted - treat as not found
                console.print(f"[yellow]Warning: Found stale release reference, but it no longer exists on GitHub[/yellow]")
                console.print(f"[red]Error updating release: {e}[/red]")
                return None

            # Fetch the release again to get the updated URL (GitHub may have changed it from untagged to tagged)
            repo = self.gh.get_repo(repo_full_name)
            try:
                updated_release = repo.get_release(tag_name)
                console.print(f"[green]Updated release: {updated_release.html_url}[/green]")
                return updated_release.html_url
            except GithubException:
                # If direct lookup fails, return the original release URL
                console.print(f"[green]Updated release: {release.html_url}[/green]")
                return release.html_url
        except GithubException as e:
            console.print(f"[red]Error updating release: {e}[/red]")
            return None

    def create_release(
        self,
        repo_full_name: str,
        version: str,
        name: str,
        body: str,
        draft: bool = False,
        prerelease: bool = False,
        target_commitish: Optional[str] = None
    ) -> Optional[str]:
        """Create a GitHub release."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            tag_name = f"{self.config.version_policy.tag_prefix}{version}"

            # Prepare arguments
            kwargs = {
                'tag': tag_name,
                'name': name,
                'message': body,
                'draft': draft,
                'prerelease': prerelease
            }
            if target_commitish:
                kwargs['target_commitish'] = target_commitish

            release = repo.create_git_release(**kwargs)

            console.print(f"[green]Created release: {release.html_url}[/green]")
            return release.html_url
        except GithubException as e:
            console.print(f"[red]Error creating release: {e}[/red]")
            return None

    def create_issue(
        self,
        repo_full_name: str,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
        milestone: Optional[Any] = None,
        issue_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a GitHub issue.

        Args:
            repo_full_name: Repository in "owner/repo" format
            title: Issue title
            body: Issue body/description
            labels: List of label names to apply
            milestone: Milestone object or number to assign
            issue_type: Issue type name (e.g. "Task", "Bug")

        Returns:
            Dictionary with 'number' and 'url' keys if successful, None otherwise
        """
        try:
            repo = self.gh.get_repo(repo_full_name)

            # Get label objects if labels specified
            label_objects = []
            if labels:
                for label_name in labels:
                    try:
                        label = repo.get_label(label_name)
                        label_objects.append(label)
                    except GithubException:
                        # Label doesn't exist, skip it or create it
                        console.print(f"[yellow]Warning: Label '{label_name}' not found in {repo_full_name}, skipping[/yellow]")

            # Prepare kwargs
            kwargs = {
                'title': title,
                'body': body,
                'labels': label_objects if label_objects else []
            }
            
            if milestone:
                kwargs['milestone'] = milestone

            # Create the issue
            issue = repo.create_issue(**kwargs)

            # Set issue type if specified
            if issue_type:
                self.set_issue_type(repo_full_name, issue.number, issue_type)

            console.print(f"[green]Created issue #{issue.number}: {issue.html_url}[/green]")
            return {
                'number': str(issue.number),
                'url': issue.html_url
            }
        except GithubException as e:
            console.print(f"[red]Error creating issue: {e}[/red]")
            return None

    def get_milestone_by_title(self, repo_full_name: str, title: str) -> Optional[Any]:
        """Get a milestone by its title."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            milestones = repo.get_milestones(state='open')
            for milestone in milestones:
                if milestone.title == title:
                    return milestone
            
            console.print(f"[yellow]Warning: Milestone '{title}' not found in {repo_full_name}[/yellow]")
            return None
        except GithubException as e:
            console.print(f"[yellow]Warning: Error fetching milestones: {e}[/yellow]")
            return None

    def create_pr_for_release_notes(
        self,
        repo_full_name: str,
        pr_title: str,
        file_path: str,
        content: str,
        branch_name: str,
        target_branch: str,
        pr_body: Optional[str] = None,
        additional_files: Optional[Dict[str, str]] = None
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
            additional_files: Optional dictionary of {path: content} for extra files

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

            # Track if any changes were made
            changes_made = False

            # Helper to update/create a file
            def update_file(path: str, file_content: str) -> bool:
                commit_msg = f"Update {path}"
                try:
                    file_contents = repo.get_contents(path, ref=branch_name)
                    
                    # Check if content is identical
                    try:
                        existing_content = file_contents.decoded_content.decode('utf-8')
                        if existing_content == file_content:
                            console.print(f"[dim]Content unchanged for {path}, skipping commit[/dim]")
                            return False
                    except Exception:
                        # If comparison fails, proceed with update
                        pass

                    # Update existing file
                    repo.update_file(
                        path,
                        commit_msg,
                        file_content,
                        file_contents.sha,
                        branch=branch_name
                    )
                    return True
                except GithubException:
                    # Create new file
                    repo.create_file(
                        path,
                        commit_msg,
                        file_content,
                        branch=branch_name
                    )
                    return True

            # Update main release notes file
            if update_file(file_path, content):
                changes_made = True

            # Update additional files if any
            if additional_files:
                for path, file_content in additional_files.items():
                    if update_file(path, file_content):
                        changes_made = True
            
            if not changes_made:
                console.print("[yellow]No changes detected in release notes (diff is empty). Skipping commit/push.[/yellow]")

            # Create PR with custom title and body
            pr_body_text = pr_body if pr_body else f"Automated release notes update"
            try:
                pr = repo.create_pull(
                    title=pr_title,
                    body=pr_body_text,
                    head=branch_name,
                    base=target_branch
                )
                console.print(f"[green]Created PR: {pr.html_url}[/green]")
                return pr.html_url
            except GithubException as e:
                if e.status == 422 and "A pull request already exists" in str(e.data):
                    console.print(f"[yellow]PR already exists for {branch_name}, finding it...[/yellow]")
                    # Find the existing PR
                    # head needs to be "owner:branch" or just "branch" depending on context
                    # Try searching for it
                    prs = repo.get_pulls(head=f"{repo.owner.login}:{branch_name}", base=target_branch, state='open')
                    if prs.totalCount > 0:
                        pr = prs[0]
                        console.print(f"[green]Found existing PR: {pr.html_url}[/green]")
                        
                        # Update PR title and body if they differ
                        if pr.title != pr_title or pr.body != pr_body_text:
                            console.print(f"[blue]Updating PR title/body...[/blue]")
                            pr.edit(title=pr_title, body=pr_body_text)
                            console.print(f"[green]Updated PR details[/green]")
                            
                        return pr.html_url
                
                # If it's another error or we couldn't find it
                console.print(f"[red]Error creating PR: {e}[/red]")
                return None
        except GithubException as e:
            console.print(f"[red]Error creating PR: {e}[/red]")
            return None

    def get_authenticated_user(self) -> Optional[str]:
        """
        Get the username of the currently authenticated user.

        Returns:
            GitHub username or None if unable to fetch
        """
        try:
            user = self.gh.get_user()
            return user.login
        except GithubException as e:
            console.print(f"[yellow]Warning: Could not fetch authenticated user: {e}[/yellow]")
            return None

    def assign_issue_to_project(
        self,
        issue_url: str,
        project_id: str,
        status: Optional[str] = None,
        custom_fields: Optional[Dict[str, str]] = None,
        debug: bool = False
    ) -> Optional[str]:
        """
        Assign an issue to a GitHub Project and optionally set fields using GraphQL API.

        Args:
            issue_url: Full URL of the issue (e.g., https://github.com/owner/repo/issues/123)
            project_id: GitHub Project Node ID (e.g. PVT_...)
            status: Status to set in the project (e.g., 'Todo', 'In Progress', 'Done')
            custom_fields: Dictionary mapping custom field names to values
            debug: Whether to show debug output

        Returns:
            Project item ID if successful, None otherwise

        Example:
            item_id = client.assign_issue_to_project(
                issue_url="https://github.com/sequentech/meta/issues/8624",
                project_id="PVT_kwDOBSDgG84ACa9s",
                status="In Progress",
                custom_fields={"Priority": "High", "Sprint": "2024-Q1"}
            )
        """
        import requests

        try:
            # Step 1: Get the issue node ID
            issue_node_id = self._get_issue_node_id(issue_url)
            if not issue_node_id:
                return None

            # Step 2: Use the provided project ID (which is now the Node ID)
            project_node_id = project_id

            # Step 3: Add the issue to the project
            item_id = self._add_issue_to_project(issue_node_id, project_node_id)
            if not item_id:
                return None

            # Step 4: Set status if provided
            if status:
                self._set_project_status(project_node_id, item_id, status, debug=debug)

            # Step 5: Set custom fields if provided
            if custom_fields:
                for field_name, field_value in custom_fields.items():
                    self._set_project_custom_field(project_node_id, item_id, field_name, field_value, debug=debug)

            return item_id

        except Exception as e:
            console.print(f"[yellow]Warning: Error assigning issue to project: {e}[/yellow]")
            return None

    def _get_issue_node_id(self, issue_url: str) -> Optional[str]:
        """Extract issue node ID from URL using GraphQL."""
        import re
        import requests

        # Parse issue owner/repo/number from URL
        match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)', issue_url)
        if not match:
            console.print(f"[yellow]Warning: Invalid issue URL format: {issue_url}[/yellow]")
            return None

        owner, repo, number = match.groups()

        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                issue(number: $number) {
                    id
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"owner": owner, "repo": repo, "number": int(number)}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[yellow]Warning: GraphQL error getting issue node ID: {data['errors']}[/yellow]")
                return None

            return data["data"]["repository"]["issue"]["id"]
        except Exception as e:
            console.print(f"[yellow]Warning: Error getting issue node ID: {e}[/yellow]")
            return None

    def get_project_node_id(self, org_name: str, project_number: int) -> Optional[str]:
        """
        Get the project node ID (PVT_...) from the project number.
        
        Args:
            org_name: Organization login (e.g. "sequentech")
            project_number: Project number (e.g. 1)
            
        Returns:
            Project node ID if found, None otherwise
        """
        import requests
        
        query = """
        query($org: String!) {
            organization(login: $org) {
                projectsV2(first: 20) {
                    nodes {
                        id
                        title
                        url
                    }
                }
            }
        }
        """
        
        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"org": org_name}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                # Check for permission errors
                for error in data.get("errors", []):
                    if "FORBIDDEN" in str(error) or "Resource not accessible by integration" in str(error):
                        console.print(f"[red]Permission denied accessing organization projects.[/red]")
                        console.print(f"[yellow]Tip: Try refreshing your token permissions:[/yellow]")
                        console.print(f"[yellow]  gh auth refresh -s read:org[/yellow]")
                
                console.print(f"[yellow]Warning: GraphQL error getting projects: {data['errors']}[/yellow]")
                return None
                
            projects = data.get("data", {}).get("organization", {}).get("projectsV2", {}).get("nodes", [])
            
            # Look for matching project number in URL
            # URL format: https://github.com/orgs/{org}/projects/{number}
            target_suffix = f"/projects/{project_number}"
            
            for project in projects:
                if project.get("url", "").endswith(target_suffix):
                    return project["id"]
                    
            console.print(f"[yellow]Project number {project_number} not found in organization {org_name}[/yellow]")
            return None
            
        except Exception as e:
            console.print(f"[yellow]Warning: Error getting project node ID: {e}[/yellow]")
            return None

    def _add_issue_to_project(self, issue_node_id: str, project_node_id: str) -> Optional[str]:
        """Add an issue to a project using GraphQL."""
        import requests

        mutation = """
        mutation($projectId: ID!, $contentId: ID!) {
            addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                item {
                    id
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": mutation, "variables": {"projectId": project_node_id, "contentId": issue_node_id}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[yellow]Warning: GraphQL error adding issue to project: {data['errors']}[/yellow]")
                return None

            item_id = data["data"]["addProjectV2ItemById"]["item"]["id"]
            console.print(f"[green]Added issue to project (internal project id: {item_id})[/green]")
            return item_id
        except Exception as e:
            console.print(f"[yellow]Warning: Error adding issue to project: {e}[/yellow]")
            return None

    def _set_project_status(self, project_node_id: str, item_id: str, status: str, debug: bool = False) -> bool:
        """Set the status field of a project item."""
        import requests

        # First, get the status field ID
        field_id = self._get_project_field_id(project_node_id, "Status")
        if not field_id:
            console.print(f"[yellow]Warning: Could not find 'Status' field in project[/yellow]")
            return False

        # Get the status option ID
        option_id = self._get_project_field_option_id(project_node_id, field_id, status, debug=debug)
        if not option_id:
            console.print(f"[yellow]Warning: Could not find status option '{status}' in project[/yellow]")
            return False

        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
            updateProjectV2ItemFieldValue(input: {
                projectId: $projectId
                itemId: $itemId
                fieldId: $fieldId
                value: $value
            }) {
                projectV2Item {
                    id
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": mutation, "variables": {
                    "projectId": project_node_id,
                    "itemId": item_id,
                    "fieldId": field_id,
                    "value": {"singleSelectOptionId": option_id}
                }},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[yellow]Warning: GraphQL error setting status: {data['errors']}[/yellow]")
                return False

            console.print(f"[green]Set project status to '{status}'[/green]")
            return True
        except Exception as e:
            console.print(f"[yellow]Warning: Error setting project status: {e}[/yellow]")
            return False

    def _set_project_custom_field(self, project_node_id: str, item_id: str, field_name: str, field_value: str, debug: bool = False) -> bool:
        """
        Set a custom field of a project item.
        
        Supports:
        - Text fields
        - Number fields
        - Date fields
        - Single Select fields
        - Iteration fields (supports "@current" to select current iteration)
        """
        import requests
        import json
        from datetime import datetime, date

        # Get field details (ID, type, options/configuration)
        field_info = self._get_project_field_details(project_node_id, field_name, debug=debug)
        if not field_info:
            console.print(f"[yellow]Warning: Could not find field '{field_name}' in project[/yellow]")
            return False

        field_id = field_info["id"]
        field_type = field_info.get("dataType", "TEXT")
        
        if debug:
            console.print(f"[dim]Field '{field_name}' type: {field_type}[/dim]")

        # Prepare the value based on field type
        value_arg = {}
        
        if field_type == "SINGLE_SELECT":
            # Find option ID
            options = field_info.get("options", [])
            option_id = None
            
            # 1. Exact match
            for opt in options:
                if opt["name"].lower() == field_value.lower():
                    option_id = opt["id"]
                    break
            
            # 2. Partial match if not found
            if not option_id:
                matches = [o for o in options if field_value.lower() in o["name"].lower()]
                if len(matches) == 1:
                    option_id = matches[0]["id"]
                    if debug:
                        console.print(f"[dim]Using partial match '{matches[0]['name']}' for '{field_value}'[/dim]")
            
            if not option_id:
                console.print(f"[yellow]Warning: Option '{field_value}' not found for field '{field_name}'[/yellow]")
                return False
                
            value_arg = {"singleSelectOptionId": option_id}
            
        elif field_type == "ITERATION":
            # Handle Iteration field
            iterations = field_info.get("configuration", {}).get("iterations", [])
            iteration_id = None
            
            # Check if user wants "Current" iteration
            if field_value.lower() in ["@current"]:
                # Find current iteration based on date
                today = date.today().isoformat()
                for iteration in iterations:
                    start_date = iteration.get("startDate")
                    duration = iteration.get("duration", 0)
                    
                    # Calculate end date (approximate, assuming duration is in days)
                    # Note: GitHub API returns duration in days
                    if start_date:
                        # We rely on GitHub's logic usually, but here we need to check locally
                        # or we could try to find one that is "active" if the API provided it
                        # But the API structure provided in _get_project_field_details needs to include dates
                        pass
                        
                # Better approach: The API usually returns iterations in order. 
                # We need to parse dates to find the current one.
                from datetime import timedelta
                
                now = datetime.now().date()
                
                for iteration in iterations:
                    start_str = iteration.get("startDate")
                    duration_days = iteration.get("duration", 14) # Default to 2 weeks if missing
                    
                    if start_str:
                        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
                        end_date = start_date + timedelta(days=duration_days)
                        
                        if start_date <= now < end_date:
                            iteration_id = iteration["id"]
                            if debug:
                                console.print(f"[dim]Found current iteration: {iteration['title']} ({start_str} - {end_date})[/dim]")
                            break
                
                if not iteration_id:
                    console.print(f"[yellow]Warning: Could not determine 'Current' iteration for field '{field_name}'[/yellow]")
                    return False
            else:
                # Find by name
                for iteration in iterations:
                    if iteration["title"].lower() == field_value.lower():
                        iteration_id = iteration["id"]
                        break
                
                if not iteration_id:
                    # Partial match
                    matches = [i for i in iterations if field_value.lower() in i["title"].lower()]
                    if len(matches) == 1:
                        iteration_id = matches[0]["id"]
                    else:
                        console.print(f"[yellow]Warning: Iteration '{field_value}' not found for field '{field_name}'[/yellow]")
                        return False
            
            value_arg = {"iterationId": iteration_id}
            
        elif field_type == "NUMBER":
            try:
                # GraphQL expects a float for number fields
                value_arg = {"number": float(field_value)}
            except ValueError:
                console.print(f"[yellow]Warning: Value '{field_value}' is not a valid number for field '{field_name}'[/yellow]")
                return False
                
        elif field_type == "DATE":
            # Validate date format YYYY-MM-DD
            try:
                datetime.strptime(field_value, "%Y-%m-%d")
                value_arg = {"date": field_value}
            except ValueError:
                console.print(f"[yellow]Warning: Value '{field_value}' is not a valid date (YYYY-MM-DD) for field '{field_name}'[/yellow]")
                return False
                
        else:
            # Default to text
            value_arg = {"text": field_value}

        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
            updateProjectV2ItemFieldValue(input: {
                projectId: $projectId
                itemId: $itemId
                fieldId: $fieldId
                value: $value
            }) {
                projectV2Item {
                    id
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            
            if debug:
                console.print(f"[dim]Setting field '{field_name}' ({field_id}) to {value_arg}[/dim]")
            
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": mutation, "variables": {
                    "projectId": project_node_id,
                    "itemId": item_id,
                    "fieldId": field_id,
                    "value": value_arg
                }},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[yellow]Warning: GraphQL error setting field '{field_name}': {data['errors']}[/yellow]")
                return False

            if debug:
                console.print(f"[green]Successfully set field '{field_name}'[/green]")
            return True
        except Exception as e:
            console.print(f"[yellow]Warning: Error setting custom field '{field_name}': {e}[/yellow]")
            return False

    def _get_project_field_details(self, project_node_id: str, field_name: str, debug: bool = False) -> Optional[dict]:
        """Get detailed information about a project field."""
        import requests
        import json

        query = """
        query($projectId: ID!) {
            node(id: $projectId) {
                ... on ProjectV2 {
                    fields(first: 20) {
                        nodes {
                            ... on ProjectV2Field {
                                id
                                name
                                dataType
                            }
                            ... on ProjectV2SingleSelectField {
                                id
                                name
                                dataType
                                options {
                                    id
                                    name
                                }
                            }
                            ... on ProjectV2IterationField {
                                id
                                name
                                dataType
                                configuration {
                                    iterations {
                                        id
                                        title
                                        startDate
                                        duration
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            
            if debug:
                console.print(f"[dim]Fetching project fields...[/dim]")
            
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"projectId": project_node_id}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[yellow]Warning: GraphQL error getting project fields: {data['errors']}[/yellow]")
                return None

            fields = data["data"]["node"]["fields"]["nodes"]
            for field in fields:
                if field.get("name").lower() == field_name.lower():
                    return field

            return None
        except Exception as e:
            console.print(f"[yellow]Warning: Error getting project field details: {e}[/yellow]")
            return None

    def _get_project_field_id(self, project_node_id: str, field_name: str) -> Optional[str]:
        """Get the field ID for a project field by name."""
        # Re-implement using the new detailed method for consistency
        details = self._get_project_field_details(project_node_id, field_name)
        return details["id"] if details else None


    def _get_project_field_option_id(self, project_node_id: str, field_id: str, option_name: str, debug: bool = False) -> Optional[str]:
        """Get the option ID for a single-select field."""
        import requests
        import json

        query = """
        query($projectId: ID!) {
            node(id: $projectId) {
                ... on ProjectV2 {
                    fields(first: 20) {
                        nodes {
                            ... on ProjectV2SingleSelectField {
                                id
                                name
                                options {
                                    id
                                    name
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            
            if debug:
                console.print(f"[dim]GraphQL Query (get options):[/dim]")
                console.print(f"[dim]{query}[/dim]")
                console.print(f"[dim]Variables: projectId={project_node_id}[/dim]")
            
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"projectId": project_node_id}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            if debug:
                console.print(f"[dim]GraphQL Response (get options):[/dim]")
                console.print(f"[dim]{json.dumps(data, indent=2)}[/dim]")

            if "errors" in data:
                console.print(f"[yellow]Warning: GraphQL error getting field options: {data['errors']}[/yellow]")
                return None

            fields = data["data"]["node"]["fields"]["nodes"]
            for field in fields:
                if field.get("id") == field_id and "options" in field:
                    options = field["options"]
                    target_name = option_name.lower()
                    
                    # 1. Exact match (case-insensitive)
                    for option in options:
                        if option["name"].lower() == target_name:
                            return option["id"]
                    
                    # 2. Partial match
                    matches = [o for o in options if target_name in o["name"].lower()]
                    
                    if len(matches) == 1:
                        matched = matches[0]
                        console.print(f"[yellow]Note: Using partial match '{matched['name']}' for status '{option_name}'[/yellow]")
                        return matched["id"]
                    elif len(matches) > 1:
                        names = [o["name"] for o in matches]
                        console.print(f"[yellow]Warning: Multiple status options match '{option_name}': {', '.join(names)}. Not applying.[/yellow]")
                        return None
                    else:
                        # No matches
                        available = [o["name"] for o in options]
                        console.print(f"[yellow]Warning: Status option '{option_name}' not found. Available: {', '.join(available)}[/yellow]")
                        return None

            return None
        except Exception as e:
            console.print(f"[yellow]Warning: Error getting field option ID: {e}[/yellow]")
            return None

    def assign_issue(
        self,
        repo_full_name: str,
        issue_number: int,
        assignee: str
    ) -> bool:
        """
        Assign an issue to a user.

        Args:
            repo_full_name: Repository in "owner/repo" format
            issue_number: Issue number
            assignee: GitHub username to assign to

        Returns:
            True if successful, False otherwise
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            issue.add_to_assignees(assignee)
            console.print(f"[green]Assigned issue #{issue_number} to @{assignee}[/green]")
            return True
        except GithubException as e:
            console.print(f"[yellow]Warning: Could not assign issue: {e}[/yellow]")
            return False

    def update_issue(
        self,
        repo_full_name: str,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None,
        milestone: Optional[Any] = None
    ) -> bool:
        """Update an existing issue."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            
            kwargs = {}
            if title is not None:
                kwargs['title'] = title
            if body is not None:
                kwargs['body'] = body
            if labels is not None:
                kwargs['labels'] = labels
            if milestone is not None:
                kwargs['milestone'] = milestone
                
            if kwargs:
                issue.edit(**kwargs)
                console.print(f"[green]Updated issue #{issue_number}[/green]")
            return True
        except GithubException as e:
            console.print(f"[red]Error updating issue #{issue_number}: {e}[/red]")
            return False

    def update_issue_body(
        self,
        repo_full_name: str,
        issue_number: int,
        body: str
    ) -> bool:
        """Update the body of an existing issue."""
        return self.update_issue(repo_full_name, issue_number, body=body)

    def set_issue_type(self, repo_full_name: str, issue_number: int, type_name: str) -> bool:
        """Set the issue type for an issue using GraphQL."""
        import requests

        owner, repo = repo_full_name.split('/')

        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                issue(number: $number) {
                    id
                }
                issueTypes(first: 20) {
                    nodes {
                        id
                        name
                    }
                }
            }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.config.github.token}",
                "Content-Type": "application/json"
            }
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"owner": owner, "repo": repo, "number": int(issue_number)}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[red]GraphQL Error fetching issue/types: {data['errors']}[/red]")
                return False

            repository = data.get("data", {}).get("repository")
            if not repository:
                return False

            issue_id = repository.get("issue", {}).get("id")
            issue_types = repository.get("issueTypes", {}).get("nodes", [])

            if not issue_id:
                console.print(f"[red]Could not find issue node ID for #{issue_number}[/red]")
                return False

            # Find the type ID
            type_id = None
            for it in issue_types:
                if it["name"].lower() == type_name.lower():
                    type_id = it["id"]
                    break

            if not type_id:
                console.print(f"[yellow]Warning: Issue type '{type_name}' not found in repository. Available types: {', '.join(t['name'] for t in issue_types)}[/yellow]")
                return False

            # Mutation to update issue type
            mutation = """
            mutation($issueId: ID!, $issueTypeId: ID!) {
                updateIssue(input: {id: $issueId, issueTypeId: $issueTypeId}) {
                    issue {
                        id
                    }
                }
            }
            """

            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": mutation, "variables": {"issueId": issue_id, "issueTypeId": type_id}},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                console.print(f"[red]GraphQL Error setting issue type: {data['errors']}[/red]")
                return False

            console.print(f"[green]Set issue type to '{type_name}'[/green]")
            return True

        except Exception as e:
            console.print(f"[yellow]Warning: Error setting issue type: {e}[/yellow]")
            return False

    def merge_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        merge_method: str = "merge",
        commit_title: Optional[str] = None,
        commit_message: Optional[str] = None
    ) -> bool:
        """
        Merge a pull request.

        This method is idempotent - if the PR is already merged, it returns True.

        Args:
            repo_full_name: Repository in "owner/repo" format
            pr_number: PR number to merge
            merge_method: Merge method - "merge", "squash", or "rebase" (default: "merge")
            commit_title: Optional custom commit title
            commit_message: Optional custom commit message

        Returns:
            True if successful (or already merged), False otherwise
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)

            # Check if already merged (idempotent)
            if pr.merged:
                console.print(f"[dim]PR #{pr_number} is already merged, skipping[/dim]")
                return True

            # Check if PR is open
            if pr.state != "open":
                console.print(f"[yellow]Warning: PR #{pr_number} is {pr.state}, cannot merge[/yellow]")
                return False

            # Merge the PR
            result = pr.merge(
                commit_title=commit_title,
                commit_message=commit_message,
                merge_method=merge_method
            )

            if result.merged:
                console.print(f"[green]✓ Merged PR #{pr_number}: {pr.title}[/green]")
                return True
            else:
                console.print(f"[red]Failed to merge PR #{pr_number}: {result.message}[/red]")
                return False

        except GithubException as e:
            console.print(f"[red]Error merging PR #{pr_number}: {e}[/red]")
            return False

    def close_issue(
        self,
        repo_full_name: str,
        issue_number: int,
        comment: Optional[str] = None
    ) -> bool:
        """
        Close an issue.

        This method is idempotent - if the issue is already closed, it returns True.

        Args:
            repo_full_name: Repository in "owner/repo" format
            issue_number: Issue number to close
            comment: Optional comment to add before closing

        Returns:
            True if successful (or already closed), False otherwise
        """
        try:
            repo = self.gh.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)

            # Check if already closed (idempotent)
            if issue.state == "closed":
                console.print(f"[dim]Issue #{issue_number} is already closed, skipping[/dim]")
                return True

            # Add comment if provided
            if comment:
                issue.create_comment(comment)

            # Close the issue
            issue.edit(state="closed")
            console.print(f"[green]✓ Closed issue #{issue_number}: {issue.title}[/green]")
            return True

        except GithubException as e:
            console.print(f"[red]Error closing issue #{issue_number}: {e}[/red]")
            return False

    def find_prs_referencing_issue(
        self,
        repo_full_name: str,
        issue_number: int,
        state: str = "all"
    ) -> List[int]:
        """
        Find all PRs that reference a specific issue in their body.

        Searches for patterns like:
        - closes #123, fixes #456, resolves #789
        - related to #123, see #456, issue #789
        - #123 (bare reference)

        Args:
            repo_full_name: Repository in "owner/repo" format
            issue_number: Issue number to search for
            state: PR state filter - "open", "closed", or "all" (default: "all")

        Returns:
            List of PR numbers that reference the issue
        """
        import re

        try:
            repo = self.gh.get_repo(repo_full_name)

            # Pattern to find issue references in PR bodies
            # Matches: closes #N, fixes #N, resolves #N, related to #N, see #N, issue #N, #N
            patterns = [
                rf'(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{issue_number}\b',
                rf'(?:related to|see|issue)\s+#{issue_number}\b',
                rf'#{issue_number}\b'
            ]

            matching_prs = []

            # Search through PRs (limit to reasonable number for performance)
            prs = repo.get_pulls(state=state, sort='updated', direction='desc')

            # Check up to 500 most recently updated PRs
            count = 0
            max_prs = 500

            for pr in prs:
                if count >= max_prs:
                    break

                count += 1
                pr_body = pr.body or ""

                # Check if any pattern matches
                for pattern in patterns:
                    if re.search(pattern, pr_body, re.IGNORECASE):
                        matching_prs.append(pr.number)
                        break  # Found match, no need to check other patterns

            if matching_prs:
                console.print(f"[dim]Found {len(matching_prs)} PR(s) referencing issue #{issue_number}[/dim]")
            else:
                console.print(f"[dim]No PRs found referencing issue #{issue_number}[/dim]")

            return matching_prs

        except GithubException as e:
            console.print(f"[yellow]Warning: Error searching for PRs: {e}[/yellow]")
            return []
