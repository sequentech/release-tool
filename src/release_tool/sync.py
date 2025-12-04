# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Sync module for highly parallelized GitHub data fetching."""

import asyncio
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, TaskID, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .config import Config
from .db import Database
from .github_utils import GitHubClient
from .models import Ticket, PullRequest

console = Console()


class SyncManager:
    """Manager for parallelized GitHub data synchronization."""

    def __init__(self, config: Config, db: Database, github_client: GitHubClient):
        self.config = config
        self.db = db
        self.github = github_client
        self.parallel_workers = config.sync.parallel_workers

    def sync_all(self) -> Dict[str, Any]:
        """
        Sync all data from GitHub (tickets, PRs, commits).

        Returns:
            Dictionary with sync statistics
        """
        stats = {
            'tickets': 0,
            'pull_requests': 0,
            'commits': 0,
            'repos_synced': set()
        }

        if self.config.sync.show_progress:
            console.print("[bold cyan]Starting GitHub data sync...[/bold cyan]")

        # Sync tickets from all ticket repos
        ticket_repos = self.config.get_ticket_repos()
        for repo_full_name in ticket_repos:
            if self.config.sync.show_progress:
                console.print(f"[cyan]Syncing tickets from {repo_full_name}...[/cyan]")

            ticket_count = self._sync_tickets_for_repo(repo_full_name)
            stats['tickets'] += ticket_count
            stats['repos_synced'].add(repo_full_name)

        # Sync PRs from code repo
        code_repo = self.config.repository.code_repo
        if self.config.sync.show_progress:
            console.print(f"[cyan]Syncing pull requests from {code_repo}...[/cyan]")

        pr_count = self._sync_pull_requests_for_repo(code_repo)
        stats['pull_requests'] = pr_count
        stats['repos_synced'].add(code_repo)

        # Sync git repository if enabled
        if self.config.sync.clone_code_repo:
            if self.config.sync.show_progress:
                console.print(f"[cyan]Syncing git repository for {code_repo}...[/cyan]")

            git_path = self._sync_git_repository(code_repo)
            stats['git_repo_path'] = git_path

        if self.config.sync.show_progress:
            console.print("[bold green]Sync completed successfully![/bold green]")
            console.print(f"  Tickets: {stats['tickets']}")
            console.print(f"  Pull Requests: {stats['pull_requests']}")
            if stats.get('git_repo_path'):
                console.print(f"  Git repo synced to: {stats['git_repo_path']}")

        stats['repos_synced'] = list(stats['repos_synced'])
        return stats

    def _sync_tickets_for_repo(self, repo_full_name: str) -> int:
        """
        Sync tickets for a specific repository with parallel fetching.

        Args:
            repo_full_name: Full repository name (owner/repo)

        Returns:
            Number of tickets synced
        """
        # Ensure repository exists in DB and get repo_id
        repo_info = self.github.get_repository_info(repo_full_name)
        repo_id = self.db.upsert_repository(repo_info)

        # Get last sync time
        last_sync = self.db.get_last_sync(repo_full_name, 'tickets')

        # Determine cutoff date
        cutoff_date = None
        cutoff_source = None
        if self.config.sync.cutoff_date:
            cutoff_date = datetime.fromisoformat(self.config.sync.cutoff_date)
            # Ensure timezone awareness (assume UTC if naive)
            if cutoff_date.tzinfo is None:
                from datetime import timezone
                cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
            cutoff_source = f"configured cutoff date: {self.config.sync.cutoff_date}"
        elif last_sync:
            # Incremental sync - fetch from last sync
            cutoff_date = last_sync
            # Ensure timezone awareness
            if cutoff_date.tzinfo is None:
                from datetime import timezone
                cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
            cutoff_source = f"last sync: {last_sync.strftime('%Y-%m-%d %H:%M:%S')}"

        if self.config.sync.show_progress:
            if cutoff_source:
                console.print(f"  [dim]Using {cutoff_source}[/dim]")
            else:
                console.print(f"  [dim]Fetching all historical tickets[/dim]")

        # Fetch tickets directly with streaming (no discovery phase)
        tickets = self._fetch_tickets_streaming(
            repo_full_name,
            repo_id,
            cutoff_date
        )

        if not tickets:
            if self.config.sync.show_progress:
                console.print(f"  [green]✓[/green] All tickets up to date (0 new)")
            return 0

        # Update sync metadata
        self.db.update_sync_metadata(
            repo_full_name,
            'tickets',
            cutoff_date=self.config.sync.cutoff_date,
            total_fetched=len(tickets)
        )

        if self.config.sync.show_progress:
            console.print(f"  [green]✓[/green] Synced {len(tickets)} tickets")

        return len(tickets)

    def _sync_pull_requests_for_repo(self, repo_full_name: str) -> int:
        """
        Sync pull requests for a specific repository with parallel fetching.

        Args:
            repo_full_name: Full repository name (owner/repo)

        Returns:
            Number of PRs synced
        """
        # Ensure repository exists in DB and get repo_id
        repo_info = self.github.get_repository_info(repo_full_name)
        repo_id = self.db.upsert_repository(repo_info)

        # Get last sync time
        last_sync = self.db.get_last_sync(repo_full_name, 'pull_requests')

        # Determine cutoff date
        cutoff_date = None
        cutoff_source = None
        if self.config.sync.cutoff_date:
            cutoff_date = datetime.fromisoformat(self.config.sync.cutoff_date)
            # Ensure timezone awareness (assume UTC if naive)
            if cutoff_date.tzinfo is None:
                from datetime import timezone
                cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
            cutoff_source = f"configured cutoff date: {self.config.sync.cutoff_date}"
        elif last_sync:
            # Incremental sync - fetch from last sync
            cutoff_date = last_sync
            # Ensure timezone awareness
            if cutoff_date.tzinfo is None:
                from datetime import timezone
                cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
            cutoff_source = f"last sync: {last_sync.strftime('%Y-%m-%d %H:%M:%S')}"

        if self.config.sync.show_progress:
            if cutoff_source:
                console.print(f"  [dim]Using {cutoff_source}[/dim]")
            else:
                console.print(f"  [dim]Fetching all historical PRs[/dim]")

        # Fetch PRs directly with streaming (no discovery phase)
        prs = self._fetch_prs_streaming(
            repo_full_name,
            repo_id,
            cutoff_date
        )

        if not prs:
            if self.config.sync.show_progress:
                console.print(f"  [green]✓[/green] All PRs up to date (0 new)")
            return 0

        # Update sync metadata
        self.db.update_sync_metadata(
            repo_full_name,
            'pull_requests',
            cutoff_date=self.config.sync.cutoff_date,
            total_fetched=len(prs)
        )

        if self.config.sync.show_progress:
            console.print(f"  [green]✓[/green] Synced {len(prs)} PRs")

        return len(prs)

    def _get_ticket_numbers_to_fetch(
        self,
        repo_full_name: str,
        cutoff_date: Optional[datetime]
    ) -> List[int]:
        """
        Get list of ticket numbers that need to be fetched.

        Args:
            repo_full_name: Full repository name
            cutoff_date: Only fetch tickets created after this date

        Returns:
            List of ticket numbers to fetch
        """
        # Get all ticket numbers from GitHub using fast Search API
        all_ticket_numbers = self.github.search_ticket_numbers(
            repo_full_name,
            since=cutoff_date
        )

        # Get ticket numbers already in DB
        existing_numbers = self.db.get_existing_ticket_numbers(repo_full_name)

        # Only fetch tickets not in DB
        to_fetch = [num for num in all_ticket_numbers if num not in existing_numbers]

        return to_fetch

    def _get_pr_numbers_to_fetch(
        self,
        repo_full_name: str,
        cutoff_date: Optional[datetime]
    ) -> List[int]:
        """
        Get list of PR numbers that need to be fetched.

        Args:
            repo_full_name: Full repository name
            cutoff_date: Only fetch PRs created after this date

        Returns:
            List of PR numbers to fetch
        """
        # Get all PR numbers from GitHub using fast Search API
        all_pr_numbers = self.github.search_pr_numbers(
            repo_full_name,
            since=cutoff_date
        )

        # Get PR numbers already in DB
        existing_numbers = self.db.get_existing_pr_numbers(repo_full_name)

        # Only fetch PRs not in DB
        to_fetch = [num for num in all_pr_numbers if num not in existing_numbers]

        return to_fetch

    def _get_clone_url(self, repo_full_name: str, method: str) -> str:
        """
        Construct clone URL based on the specified method.

        Args:
            repo_full_name: Full repository name (owner/repo)
            method: Clone method ('https', 'ssh', or 'auto')

        Returns:
            Clone URL string
        """
        # Use custom template if provided
        if self.config.sync.clone_url_template:
            url = self.config.sync.clone_url_template.format(repo_full_name=repo_full_name)
            if self.config.sync.show_progress:
                console.print(f"  [dim]Using custom clone URL template[/dim]")
            return url

        # Use method-specific URL format
        if method == 'ssh':
            url = f"git@github.com:{repo_full_name}.git"
            if self.config.sync.show_progress:
                console.print(f"  [dim]Clone URL (SSH): {url}[/dim]")
            return url
        else:  # https or auto
            # Check if token is valid (not None and not empty string)
            if self.config.github.token and self.config.github.token.strip():
                # Mask token for debug output
                token = self.config.github.token
                masked_token = f"{token[:7]}...{token[-4:]}" if len(token) > 11 else "***"
                url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
                if self.config.sync.show_progress:
                    console.print(f"  [dim]Clone URL (HTTPS): https://x-access-token:{masked_token}@github.com/{repo_full_name}.git[/dim]")
                    console.print(f"  [dim]Token length: {len(token)} chars[/dim]")
                return url
            else:
                url = f"https://github.com/{repo_full_name}.git"
                if self.config.sync.show_progress:
                    console.print(f"  [yellow]Clone URL (HTTPS, no token): {url}[/yellow]")
                    console.print(f"  [yellow]Warning: No GitHub token available, private repos will fail[/yellow]")
                return url

    def _sync_git_repository(self, repo_full_name: str) -> str:
        """
        Clone or update the git repository for offline operation.

        Args:
            repo_full_name: Full repository name (owner/repo)

        Returns:
            Path to the synced git repository
        """
        repo_path = Path(self.config.get_code_repo_path())

        # Check if repo already exists
        if repo_path.exists() and (repo_path / '.git').exists():
            # Repository exists - update it
            if self.config.sync.show_progress:
                console.print(f"  [dim]Updating existing repository at {repo_path}[/dim]")

            try:
                # Fetch all updates
                subprocess.run(
                    ['git', 'fetch', '--all', '--tags', '--prune'],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )

                # Reset to latest version of default branch
                # Use branch_policy.default_branch (fallback to repository.default_branch for backward compatibility)
                default_branch = self.config.branch_policy.default_branch
                if self.config.repository.default_branch:
                    # Legacy config support
                    default_branch = self.config.repository.default_branch
                subprocess.run(
                    ['git', 'reset', '--hard', f'origin/{default_branch}'],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )

                if self.config.sync.show_progress:
                    console.print(f"  [green]✓[/green] Updated repository")

            except subprocess.CalledProcessError as e:
                console.print(f"[yellow]Warning: Failed to update repository: {e}[/yellow]")
                console.print(f"[yellow]Error output: {e.stderr}[/yellow]")

        else:
            # Repository doesn't exist - clone it
            if self.config.sync.show_progress:
                console.print(f"  [dim]Cloning repository to {repo_path}[/dim]")

            # Ensure parent directory exists
            repo_path.parent.mkdir(parents=True, exist_ok=True)

            # If directory exists but is not a git repo (checked above), remove it
            if repo_path.exists():
                shutil.rmtree(repo_path)

            clone_method = self.config.sync.clone_method
            last_error = None

            # Try cloning with the configured method
            methods_to_try = []
            if clone_method == 'auto':
                # Try HTTPS first (with token if available), then SSH
                methods_to_try = ['https', 'ssh']
            else:
                methods_to_try = [clone_method]

            if self.config.sync.show_progress:
                console.print(f"  [dim]Clone method: {clone_method}[/dim]")
                console.print(f"  [dim]Will try methods in order: {', '.join(methods_to_try)}[/dim]")
                console.print(f"  [dim]Repository: {repo_full_name}[/dim]")

            for method in methods_to_try:
                try:
                    clone_url = self._get_clone_url(repo_full_name, method)

                    if self.config.sync.show_progress and len(methods_to_try) > 1:
                        console.print(f"  [dim]Trying {method.upper()} clone...[/dim]")

                    # Show the git command (with masked token)
                    if self.config.sync.show_progress:
                        masked_url = clone_url
                        if 'x-access-token:' in clone_url:
                            # Mask the token in the URL
                            parts = clone_url.split('x-access-token:')
                            if len(parts) > 1:
                                token_and_rest = parts[1]
                                token_end = token_and_rest.index('@')
                                token = token_and_rest[:token_end]
                                masked = f"{token[:7]}...{token[-4:]}" if len(token) > 11 else "***"
                                masked_url = f"{parts[0]}x-access-token:{masked}{token_and_rest[token_end:]}"
                        console.print(f"  [dim]Running: git clone {masked_url} {repo_path}[/dim]")

                    result = subprocess.run(
                        ['git', 'clone', clone_url, str(repo_path)],
                        check=True,
                        capture_output=True,
                        text=True
                    )

                    if self.config.sync.show_progress:
                        console.print(f"  [green]✓[/green] Cloned repository using {method.upper()}")
                        if result.stdout:
                            console.print(f"  [dim]Git output: {result.stdout.strip()}[/dim]")

                    return str(repo_path)

                except subprocess.CalledProcessError as e:
                    last_error = e
                    if self.config.sync.show_progress:
                        console.print(f"  [red]Git clone failed with exit code {e.returncode}[/red]")
                        if e.stdout:
                            console.print(f"  [red]Git stdout: {e.stdout.strip()}[/red]")
                        if e.stderr:
                            console.print(f"  [red]Git stderr: {e.stderr.strip()}[/red]")

                    if len(methods_to_try) > 1:
                        # In auto mode, try next method
                        if self.config.sync.show_progress:
                            console.print(f"  [yellow]Failed with {method.upper()}, trying next method...[/yellow]")
                        continue
                    else:
                        # Only one method configured, fail immediately
                        break

            # All methods failed
            error_msg = f"Failed to clone repository using {', '.join(methods_to_try).upper()}"
            console.print(f"[red]Error: {error_msg}[/red]")
            if last_error:
                console.print(f"[red]Last error output: {last_error.stderr}[/red]")

            # Provide helpful suggestions
            console.print("\n[yellow]Troubleshooting tips:[/yellow]")
            if 'https' in methods_to_try:
                if self.config.github.token and self.config.github.token.strip():
                    console.print("  - Check that GITHUB_TOKEN has 'contents: read' permission")
                    console.print("  - Verify the token is valid and not expired")
                else:
                    console.print("  - Set GITHUB_TOKEN environment variable for private repositories")
                    console.print("  - Example: export GITHUB_TOKEN='ghp_your_token'")
            if 'ssh' in methods_to_try:
                console.print("  - Ensure SSH keys are configured: ssh -T git@github.com")
                console.print("  - For GitHub Actions, add SSH key using webfactory/ssh-agent action")

            raise RuntimeError(error_msg)

        return str(repo_path)

    def _fetch_tickets_streaming(
        self,
        repo_full_name: str,
        repo_id: int,
        cutoff_date: Optional[datetime]
    ) -> List[Ticket]:
        """
        Fetch tickets efficiently using Core API with paginated batch fetching.

        Uses GET /repos/{owner}/{repo}/issues with per_page=100 to fetch full issue data
        in batches, then filters against existing tickets in DB.

        Args:
            repo_full_name: Full repository name
            repo_id: Repository ID in database
            cutoff_date: Only fetch tickets created after this date

        Returns:
            List of fetched tickets
        """
        try:
            existing_numbers = self.db.get_existing_ticket_numbers(repo_full_name)

            # Fetch all issues in one pass with paginated batches (100 per request)
            all_tickets = self.github.fetch_all_issues(repo_full_name, repo_id, since=cutoff_date)

            # Filter out existing
            if self.config.sync.show_progress and all_tickets:
                console.print(f"  [dim]Filtering {len(all_tickets)} issues against existing {len(existing_numbers)} in database...[/dim]")
            new_tickets = [ticket for ticket in all_tickets if ticket.number not in existing_numbers]

            if not new_tickets:
                if self.config.sync.show_progress:
                    console.print(f"  [dim]No new tickets to sync[/dim]")
                return []

            if self.config.sync.show_progress:
                console.print(f"  [cyan]Storing {len(new_tickets)} new tickets...[/cyan]")

            # Insert tickets to database
            for ticket in new_tickets:
                self.db.upsert_ticket(ticket)

            if self.config.sync.show_progress:
                console.print(f"  [green]✓[/green] Synced {len(new_tickets)} new tickets")

            return new_tickets

        except Exception as e:
            console.print(f"[red]Error fetching tickets: {e}[/red]")
            return []

    def _fetch_prs_streaming(
        self,
        repo_full_name: str,
        repo_id: int,
        cutoff_date: Optional[datetime]
    ) -> List[PullRequest]:
        """
        Fetch PRs efficiently using Core API with paginated batch fetching.

        Uses GET /repos/{owner}/{repo}/pulls with per_page=100 to fetch full PR data
        in batches, then filters for merged PRs and against existing PRs in DB.

        Args:
            repo_full_name: Full repository name
            repo_id: Repository ID in database
            cutoff_date: Only fetch PRs merged after this date

        Returns:
            List of fetched PRs
        """
        try:
            existing_numbers = self.db.get_existing_pr_numbers(repo_full_name)

            # Fetch all PRs in one pass with paginated batches (100 per request)
            all_prs = self.github.fetch_all_pull_requests(repo_full_name, repo_id, since=cutoff_date)

            # Filter to only merged PRs and respect cutoff date
            merged_prs = [
                pr for pr in all_prs
                if pr.merged_at and (cutoff_date is None or pr.merged_at >= cutoff_date)
            ]

            # Filter out existing
            if self.config.sync.show_progress and merged_prs:
                console.print(f"  [dim]Filtering {len(merged_prs)} merged PRs against existing {len(existing_numbers)} in database...[/dim]")
            new_prs = [pr for pr in merged_prs if pr.number not in existing_numbers]

            if not new_prs:
                if self.config.sync.show_progress:
                    console.print(f"  [dim]No new PRs to sync[/dim]")
                return []

            if self.config.sync.show_progress:
                console.print(f"  [cyan]Storing {len(new_prs)} new PRs...[/cyan]")

            # Insert PRs to database
            for pr in new_prs:
                self.db.upsert_pull_request(pr)

            if self.config.sync.show_progress:
                console.print(f"  [green]✓[/green] Synced {len(new_prs)} new PRs")

            return new_prs

        except Exception as e:
            console.print(f"[red]Error fetching PRs: {e}[/red]")
            return []
