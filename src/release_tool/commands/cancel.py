# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Cancel command for release-tool.

This command cancels a release by:
1. Closing the associated PR (if provided or found)
2. Deleting the PR branch
3. Deleting the GitHub release
4. Deleting the git tag
5. Deleting database records
6. Closing the related issue (if provided or found)

All operations are idempotent and will succeed if resources don't exist.
"""

import sys
from typing import Optional, Tuple
import click
from rich.console import Console
from rich.prompt import Confirm

from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..models import SemanticVersion

console = Console()


def _resolve_version_pr_issue(
    db: Database,
    repo_id: int,
    repo_full_name: str,
    version: Optional[str],
    pr_number: Optional[int],
    issue_number: Optional[int],
    debug: bool = False
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Auto-detect version, PR, and issue if not provided.

    Args:
        db: Database instance
        repo_id: Repository ID
        repo_full_name: Full repository name
        version: Optional version string
        pr_number: Optional PR number
        issue_number: Optional issue number
        debug: Enable debug output

    Returns:
        Tuple of (version, pr_number, issue_number)
    """
    # If version provided, try to find PR/issue from database
    if version:
        if debug:
            console.print(f"[dim]Searching for PR and issue for version {version}...[/dim]")

        # Try to find PR by searching for PRs with version in title/branch
        if not pr_number:
            prs = db.find_prs_for_issue(repo_full_name, 0, limit=100)  # Get all PRs
            for pr in prs:
                if version in pr.get('title', '') or version in pr.get('body', ''):
                    pr_number = pr.get('number')
                    if debug:
                        console.print(f"[dim]Found PR #{pr_number} from database[/dim]")
                    break

        # Try to find issue from database associations
        if not issue_number:
            issue_assoc = db.get_issue_association(repo_full_name, version)
            if issue_assoc and issue_assoc.get('issue_number'):
                issue_number = issue_assoc['issue_number']
                if debug:
                    console.print(f"[dim]Found issue #{issue_number} from database[/dim]")

    # If PR provided but no version, try to extract from PR
    elif pr_number:
        if debug:
            console.print(f"[dim]Searching for version from PR #{pr_number}...[/dim]")

        # Try to get PR from database
        pr = db.get_pull_request(repo_id, pr_number)
        if pr:
            # Try to extract version from PR title
            import re
            title = pr.title if hasattr(pr, 'title') else ''
            match = re.search(r'v?(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.\d+)?)?)', title)
            if match:
                version = match.group(1)
                if debug:
                    console.print(f"[dim]Extracted version {version} from PR title[/dim]")

    # If issue provided but no version, try to extract from issue
    elif issue_number:
        if debug:
            console.print(f"[dim]Searching for version from issue #{issue_number}...[/dim]")

        # Try to get issue from database
        issue = db.get_issue(repo_id, issue_number)
        if issue:
            # Try to extract version from issue title
            import re
            title = issue.title if hasattr(issue, 'title') else ''
            match = re.search(r'v?(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.\d+)?)?)', title)
            if match:
                version = match.group(1)
                if debug:
                    console.print(f"[dim]Extracted version {version} from issue title[/dim]")

    return version, pr_number, issue_number


def _check_published_status(
    db: Database,
    repo_id: int,
    version: str,
    force: bool,
    debug: bool = False
) -> bool:
    """
    Check if release is published and handle accordingly.

    Args:
        db: Database instance
        repo_id: Repository ID
        version: Version string
        force: Force flag
        debug: Enable debug output

    Returns:
        True if should proceed, False if should block
    """
    # Get release from database
    release = db.get_release(repo_id, version)
    if not release:
        if debug:
            console.print(f"[dim]No release found in database for {version}[/dim]")
        return True

    # Check if published
    if release.published_at:
        if force:
            console.print(f"[yellow]⚠ Warning: Release {version} is published. Proceeding due to --force flag.[/yellow]")
            return True
        else:
            console.print(f"[red]Error: Release {version} is already published.[/red]")
            console.print(f"[red]Use --force to cancel a published release.[/red]")
            return False

    return True


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('version', required=False)
@click.option(
    '--issue',
    '-i',
    type=int,
    help='Issue number to close'
)
@click.option(
    '--pr',
    '-p',
    type=int,
    help='Pull request number to close'
)
@click.option(
    '--force',
    '-f',
    is_flag=True,
    help='Force cancel even if release is published'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Show what would be deleted without actually deleting'
)
@click.pass_context
def cancel(
    ctx,
    version: Optional[str],
    issue: Optional[int],
    pr: Optional[int],
    force: bool,
    dry_run: bool
):
    """
    Cancel a release by deleting all associated resources.

    This command will:
    1. Close the associated PR (if exists)
    2. Delete the PR branch
    3. Delete the GitHub release
    4. Delete the git tag
    5. Delete database records
    6. Close the related issue (if exists)

    All operations are idempotent and stop on first failure.

    Examples:

      release-tool cancel 1.2.3-rc.1              # Cancel draft release

      release-tool cancel 1.2.3 --force           # Cancel published release

      release-tool cancel 1.2.3 --pr 42 --issue 1 # Cancel with specific PR and issue

      release-tool cancel 1.2.3 --dry-run         # Show what would be deleted
    """
    config: Config = ctx.obj['config']
    debug = ctx.obj.get('debug', False)
    assume_yes = ctx.obj.get('assume_yes', False)

    repo_full_name = config.repository.code_repo

    # Connect to database
    db = Database(config.database.path)
    db.connect()

    try:
        # Get repository
        repo = db.get_repository(repo_full_name)
        if not repo:
            console.print(f"[red]Error: Repository {repo_full_name} not found in database.[/red]")
            console.print(f"[yellow]Run 'release-tool pull' first to initialize the database.[/yellow]")
            sys.exit(1)

        repo_id = repo.id

        # Auto-detect version, PR, and issue if not all provided
        version, pr_number, issue_number = _resolve_version_pr_issue(
            db, repo_id, repo_full_name, version, pr, issue, debug
        )

        # Require at least version or (PR and/or issue)
        if not version and not pr_number and not issue_number:
            console.print("[red]Error: Must provide version, --pr, or --issue[/red]")
            console.print("Run with --help for usage information")
            sys.exit(1)

        # If we have version, check if published
        if version:
            if not _check_published_status(db, repo_id, version, force, debug):
                sys.exit(1)

        # Add 'v' prefix to tag name if needed
        tag_name = f"v{version}" if version and not version.startswith('v') else version

        # Show what will be cancelled
        if dry_run:
            console.print("[bold yellow]DRY RUN - No changes will be made[/bold yellow]")
        else:
            console.print(f"[bold]Cancelling release {version or '(auto-detect)'}[/bold]")

        console.print("\n[bold]Will perform the following operations:[/bold]")
        if pr_number:
            console.print(f"  • Close PR #{pr_number} and delete branch")
        if version:
            console.print(f"  • Delete GitHub release for tag {tag_name}")
            console.print(f"  • Delete git tag {tag_name}")
            console.print(f"  • Delete database records for version {version}")
        if issue_number:
            console.print(f"  • Close issue #{issue_number}")

        console.print()

        # Confirm unless --dry-run, --assume-yes, or --auto
        if not dry_run and not assume_yes and not ctx.obj.get('auto', False):
            if not Confirm.ask("[yellow]Proceed with cancellation?[/yellow]"):
                console.print("[yellow]Cancelled by user.[/yellow]")
                sys.exit(0)

        # Exit early if dry-run
        if dry_run:
            console.print("\n[dim]Dry run complete. Use without --dry-run to execute.[/dim]")
            sys.exit(0)

        # Create GitHub client
        github_client = GitHubClient(config.github.token)

        success_operations = []
        failed_operations = []

        # Operation 1: Close PR (if provided)
        if pr_number:
            console.print(f"\n[bold]Closing PR #{pr_number}...[/bold]")

            # Get PR details to find branch name
            pr_obj = github_client.get_pull_request(repo_full_name, pr_number)
            branch_name = None

            if pr_obj:
                branch_name = pr_obj.head.ref
                console.print(f"  PR branch: {branch_name}")

            # Close the PR
            comment = f"Closing PR as release {version or 'this release'} is being cancelled."
            if github_client.close_pull_request(repo_full_name, pr_number, comment):
                console.print(f"  ✓ Closed PR #{pr_number}")
                success_operations.append(f"Close PR #{pr_number}")
            else:
                console.print(f"  [red]✗ Failed to close PR #{pr_number}[/red]")
                failed_operations.append(f"Close PR #{pr_number}")
                console.print("[red]Stopping due to failure.[/red]")
                sys.exit(1)

            # Operation 2: Delete branch
            if branch_name:
                console.print(f"\n[bold]Deleting branch {branch_name}...[/bold]")
                if github_client.delete_branch(repo_full_name, branch_name):
                    console.print(f"  ✓ Deleted branch {branch_name}")
                    success_operations.append(f"Delete branch {branch_name}")
                else:
                    console.print(f"  [red]✗ Failed to delete branch {branch_name}[/red]")
                    failed_operations.append(f"Delete branch {branch_name}")
                    console.print("[red]Stopping due to failure.[/red]")
                    sys.exit(1)

        # Operation 3: Delete GitHub release
        if version and tag_name:
            console.print(f"\n[bold]Deleting GitHub release {tag_name}...[/bold]")
            if github_client.delete_release(repo_full_name, tag_name):
                console.print(f"  ✓ Deleted GitHub release {tag_name}")
                success_operations.append(f"Delete release {tag_name}")
            else:
                console.print(f"  [red]✗ Failed to delete GitHub release {tag_name}[/red]")
                failed_operations.append(f"Delete release {tag_name}")
                console.print("[red]Stopping due to failure.[/red]")
                sys.exit(1)

        # Operation 4: Delete git tag
        if version and tag_name:
            console.print(f"\n[bold]Deleting git tag {tag_name}...[/bold]")
            if github_client.delete_tag(repo_full_name, tag_name):
                console.print(f"  ✓ Deleted git tag {tag_name}")
                success_operations.append(f"Delete tag {tag_name}")
            else:
                console.print(f"  [red]✗ Failed to delete git tag {tag_name}[/red]")
                failed_operations.append(f"Delete tag {tag_name}")
                console.print("[red]Stopping due to failure.[/red]")
                sys.exit(1)

        # Operation 5: Delete database records
        if version:
            console.print(f"\n[bold]Deleting database records for {version}...[/bold]")
            try:
                # Delete release record
                if db.delete_release(repo_id, version):
                    console.print(f"  ✓ Deleted database records for {version}")
                    success_operations.append(f"Delete database records for {version}")
                else:
                    console.print(f"  [red]✗ Failed to delete database records[/red]")
                    failed_operations.append(f"Delete database records for {version}")
                    console.print("[red]Stopping due to failure.[/red]")
                    sys.exit(1)
            except Exception as e:
                console.print(f"  [red]✗ Failed to delete database records: {e}[/red]")
                failed_operations.append(f"Delete database records for {version}")
                console.print("[red]Stopping due to failure.[/red]")
                sys.exit(1)

        # Operation 6: Close issue (if provided)
        if issue_number:
            console.print(f"\n[bold]Closing issue #{issue_number}...[/bold]")
            comment = f"Closing issue as release {version or 'this release'} is being cancelled."
            if github_client.close_issue(repo_full_name, issue_number, comment):
                console.print(f"  ✓ Closed issue #{issue_number}")
                success_operations.append(f"Close issue #{issue_number}")
            else:
                console.print(f"  [red]✗ Failed to close issue #{issue_number}[/red]")
                failed_operations.append(f"Close issue #{issue_number}")
                console.print("[red]Stopping due to failure.[/red]")
                sys.exit(1)

        # Success summary
        console.print(f"\n[bold green]✓ Successfully cancelled release {version or ''}[/bold green]")
        console.print(f"[dim]Operations completed: {len(success_operations)}[/dim]")

    finally:
        db.close()
