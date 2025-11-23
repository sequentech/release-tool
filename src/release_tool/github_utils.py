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
        self.gh = Github(token, base_url=config.github.api_url)

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
            batch_size = 50
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
        with ThreadPoolExecutor(max_workers=10) as executor:
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
            return Author(
                username=gh_user.login,
                github_id=gh_user.id,
                name=gh_user.name,  # May be None
                email=gh_user.email,  # May be None (depends on privacy settings)
                display_name=gh_user.name or gh_user.login,
                avatar_url=gh_user.avatar_url,
                profile_url=gh_user.html_url,
                company=gh_user.company,
                location=gh_user.location,
                bio=gh_user.bio,
                blog=gh_user.blog,
                user_type=gh_user.type  # "User", "Bot", "Organization"
            )
        except Exception as e:
            console.print(f"[yellow]Warning: Error creating author from GitHub user: {e}[/yellow]")
            # Return minimal author with just username
            return Author(username=gh_user.login if hasattr(gh_user, 'login') else None)

    def _pr_to_model(self, gh_pr, repo_id: int) -> PullRequest:
        """Convert PyGithub PR to our model."""
        labels = [
            Label(name=label.name, color=label.color, description=label.description)
            for label in gh_pr.labels
        ]

        return PullRequest(
            repo_id=repo_id,
            number=gh_pr.number,
            title=gh_pr.title,
            body=gh_pr.body,
            state=gh_pr.state,
            merged_at=gh_pr.merged_at,
            author=self._github_user_to_author(gh_pr.user),
            base_branch=gh_pr.base.ref if gh_pr.base else None,
            head_branch=gh_pr.head.ref if gh_pr.head else None,
            head_sha=gh_pr.head.sha if gh_pr.head else None,
            labels=labels,
            url=gh_pr.html_url
        )

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
                key=f"#{issue.number}",
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

    def search_ticket_numbers(
        self,
        repo_full_name: str,
        since: Optional[datetime] = None
    ) -> List[int]:
        """
        Search for ticket numbers using GitHub Search API (FAST - single API call per page).

        Args:
            repo_full_name: Full repository name (owner/repo)
            since: Only include tickets created after this datetime

        Returns:
            List of ticket numbers
        """
        try:
            # Build search query
            query = f"repo:{repo_full_name} is:issue"
            if since:
                query += f" created:>={since.strftime('%Y-%m-%d')}"

            # Use search API (much faster than iterating)
            issues = self.gh.search_issues(query, sort='created', order='desc')

            ticket_numbers = []
            for issue in issues:
                ticket_numbers.append(issue.number)

                if len(ticket_numbers) % 500 == 0:
                    console.print(f"  [dim]Found {len(ticket_numbers)} tickets...[/dim]")

            return ticket_numbers
        except GithubException as e:
            console.print(f"[red]Error searching tickets from {repo_full_name}: {e}[/red]")
            return []

    def search_pr_numbers(
        self,
        repo_full_name: str,
        since: Optional[datetime] = None
    ) -> List[int]:
        """
        Search for merged PR numbers using GitHub Search API (FAST - single API call per page).

        Args:
            repo_full_name: Full repository name (owner/repo)
            since: Only include PRs created after this datetime

        Returns:
            List of PR numbers
        """
        try:
            # Build search query for merged PRs only
            query = f"repo:{repo_full_name} is:pr is:merged"
            if since:
                query += f" merged:>={since.strftime('%Y-%m-%d')}"

            # Use search API (much faster than iterating)
            prs = self.gh.search_issues(query, sort='created', order='desc')

            pr_numbers = []
            for pr in prs:
                pr_numbers.append(pr.number)

                if len(pr_numbers) % 500 == 0:
                    console.print(f"  [dim]Found {len(pr_numbers)} merged PRs...[/dim]")

            return pr_numbers
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
        """Fetch releases from GitHub."""
        try:
            repo = self.gh.get_repo(repo_full_name)
            releases = []

            for gh_release in repo.get_releases():
                release = Release(
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
