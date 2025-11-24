"""Sync module for highly parallelized GitHub data fetching."""

import asyncio
import subprocess
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
            cutoff_source = f"configured cutoff date: {self.config.sync.cutoff_date}"
        elif last_sync:
            # Incremental sync - fetch from last sync
            cutoff_date = last_sync
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
            cutoff_source = f"configured cutoff date: {self.config.sync.cutoff_date}"
        elif last_sync:
            # Incremental sync - fetch from last sync
            cutoff_date = last_sync
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

    def _fetch_tickets_parallel(
        self,
        repo_full_name: str,
        repo_id: int,
        ticket_numbers: List[int]
    ) -> List[Ticket]:
        """
        Fetch tickets in parallel with progress updates.

        Args:
            repo_full_name: Full repository name
            repo_id: Repository ID in database
            ticket_numbers: List of ticket numbers to fetch

        Returns:
            List of fetched tickets
        """
        tickets = []
        total = len(ticket_numbers)

        if self.config.sync.show_progress:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task(
                    f"Fetching tickets from {repo_full_name}",
                    total=total
                )

                with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                    # Submit all tasks
                    future_to_number = {
                        executor.submit(
                            self.github.fetch_issue,
                            repo_full_name,
                            num,
                            repo_id
                        ): num
                        for num in ticket_numbers
                    }

                    # Collect results as they complete
                    for future in as_completed(future_to_number):
                        ticket = future.result()
                        if ticket:
                            tickets.append(ticket)

                        # Update progress
                        progress.update(task, advance=1)
                        completed = len([f for f in future_to_number if f.done()])
                        progress.update(
                            task,
                            description=f"Fetching tickets from {repo_full_name} ({completed}/{total})"
                        )
        else:
            # No progress display - just fetch in parallel
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                future_to_number = {
                    executor.submit(
                        self.github.fetch_issue,
                        repo_full_name,
                        num,
                        repo_id
                    ): num
                    for num in ticket_numbers
                }

                for future in as_completed(future_to_number):
                    ticket = future.result()
                    if ticket:
                        tickets.append(ticket)

        return tickets

    def _fetch_prs_parallel(
        self,
        repo_full_name: str,
        repo_id: int,
        pr_numbers: List[int]
    ) -> List[PullRequest]:
        """
        Fetch pull requests in parallel with progress updates.

        Args:
            repo_full_name: Full repository name
            repo_id: Repository ID in database
            pr_numbers: List of PR numbers to fetch

        Returns:
            List of fetched pull requests
        """
        prs = []
        total = len(pr_numbers)

        if self.config.sync.show_progress:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task(
                    f"Fetching PRs from {repo_full_name}",
                    total=total
                )

                with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                    # Create a helper function that wraps get_pull_request with repo_id
                    def fetch_pr_with_repo_id(num):
                        pr = self.github.get_pull_request(repo_full_name, num)
                        if pr:
                            # Update repo_id
                            pr.repo_id = repo_id
                        return pr

                    # Submit all tasks
                    future_to_number = {
                        executor.submit(fetch_pr_with_repo_id, num): num
                        for num in pr_numbers
                    }

                    # Collect results as they complete
                    for future in as_completed(future_to_number):
                        pr = future.result()
                        if pr:
                            prs.append(pr)

                        # Update progress
                        progress.update(task, advance=1)
                        completed = len([f for f in future_to_number if f.done()])
                        progress.update(
                            task,
                            description=f"Fetching PRs from {repo_full_name} ({completed}/{total})"
                        )
        else:
            # No progress display - just fetch in parallel
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                def fetch_pr_with_repo_id(num):
                    pr = self.github.get_pull_request(repo_full_name, num)
                    if pr:
                        pr.repo_id = repo_id
                    return pr

                future_to_number = {
                    executor.submit(fetch_pr_with_repo_id, num): num
                    for num in pr_numbers
                }

                for future in as_completed(future_to_number):
                    pr = future.result()
                    if pr:
                        prs.append(pr)

        return prs

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

            try:
                # Construct clone URL (use https with token if available)
                if self.config.github.token:
                    clone_url = f"https://{self.config.github.token}@github.com/{repo_full_name}.git"
                else:
                    clone_url = f"https://github.com/{repo_full_name}.git"

                subprocess.run(
                    ['git', 'clone', clone_url, str(repo_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )

                if self.config.sync.show_progress:
                    console.print(f"  [green]✓[/green] Cloned repository")

            except subprocess.CalledProcessError as e:
                console.print(f"[red]Error: Failed to clone repository: {e}[/red]")
                console.print(f"[red]Error output: {e.stderr}[/red]")
                raise

        return str(repo_path)

    def _fetch_tickets_streaming(
        self,
        repo_full_name: str,
        repo_id: int,
        cutoff_date: Optional[datetime]
    ) -> List[Ticket]:
        """
        Fetch tickets with parallel API calls - fetch and filter simultaneously.

        Args:
            repo_full_name: Full repository name
            repo_id: Repository ID in database
            cutoff_date: Only fetch tickets created after this date

        Returns:
            List of fetched tickets
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            existing_numbers = self.db.get_existing_ticket_numbers(repo_full_name)

            # Use fast Search API to get ticket numbers
            all_ticket_numbers = self.github.search_ticket_numbers(repo_full_name, since=cutoff_date)

            # Filter out existing
            if self.config.sync.show_progress and all_ticket_numbers:
                console.print(f"  [dim]Filtering {len(all_ticket_numbers)} tickets against existing {len(existing_numbers)} in database...[/dim]")
            ticket_numbers = [num for num in all_ticket_numbers if num not in existing_numbers]

            if not ticket_numbers:
                return []

            if self.config.sync.show_progress:
                console.print(f"  [cyan]Fetching {len(ticket_numbers)} new tickets in parallel...[/cyan]")

            # Fetch full ticket details in parallel
            tickets = []

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task(
                    "Fetching tickets...",
                    total=len(ticket_numbers)
                )

                with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                    # Submit all fetch tasks in parallel
                    future_to_number = {
                        executor.submit(
                            self.github.fetch_issue,
                            repo_full_name,
                            num,
                            repo_id
                        ): num
                        for num in ticket_numbers
                    }

                    # Collect and store results as they complete
                    completed = 0
                    for future in as_completed(future_to_number):
                        try:
                            ticket = future.result()
                            if ticket:
                                tickets.append(ticket)
                                self.db.upsert_ticket(ticket)

                            completed += 1
                            progress.update(
                                task,
                                advance=1,
                                description=f"Fetched {completed}/{len(ticket_numbers)} tickets"
                            )
                        except Exception as e:
                            console.print(f"[yellow]Warning: Error fetching ticket: {e}[/yellow]")
                            progress.update(task, advance=1)

            return tickets

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
        Fetch PRs with parallel API calls - fetch and filter simultaneously.

        Args:
            repo_full_name: Full repository name
            repo_id: Repository ID in database
            cutoff_date: Only fetch PRs created after this date

        Returns:
            List of fetched PRs
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            existing_numbers = self.db.get_existing_pr_numbers(repo_full_name)

            # Use fast Search API to get PR numbers
            all_pr_numbers = self.github.search_pr_numbers(repo_full_name, since=cutoff_date)

            # Filter out existing
            if self.config.sync.show_progress and all_pr_numbers:
                console.print(f"  [dim]Filtering {len(all_pr_numbers)} PRs against existing {len(existing_numbers)} in database...[/dim]")
            pr_numbers = [num for num in all_pr_numbers if num not in existing_numbers]

            if not pr_numbers:
                return []

            if self.config.sync.show_progress:
                console.print(f"  [cyan]Fetching {len(pr_numbers)} new PRs in parallel...[/cyan]")

            # Fetch full PR details in parallel
            prs = []

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task(
                    "Fetching PRs...",
                    total=len(pr_numbers)
                )

                with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                    # Submit all fetch tasks in parallel
                    future_to_number = {
                        executor.submit(
                            self.github.get_pull_request,
                            repo_full_name,
                            num
                        ): num
                        for num in pr_numbers
                    }

                    # Collect and store results as they complete
                    completed = 0
                    for future in as_completed(future_to_number):
                        try:
                            pr = future.result()
                            if pr:
                                pr.repo_id = repo_id
                                prs.append(pr)
                                self.db.upsert_pull_request(pr)

                            completed += 1
                            progress.update(
                                task,
                                advance=1,
                                description=f"Fetched {completed}/{len(pr_numbers)} PRs"
                            )
                        except Exception as e:
                            console.print(f"[yellow]Warning: Error fetching PR: {e}[/yellow]")
                            progress.update(task, advance=1)

            return prs

        except Exception as e:
            console.print(f"[red]Error fetching PRs: {e}[/red]")
            return []
