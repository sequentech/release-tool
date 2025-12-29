# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Cancel command for release-tool.

This command cancels a release by:
1. Closing the associated PR (if exists and not merged)
2. Deleting the PR branch (if exists)
3. Deleting the GitHub release
4. Deleting the git tag
5. Deleting database records
6. Closing the related issue (if exists)
"""

import sys
from typing import Optional, Tuple
from pathlib import Path
import click
from rich.console import Console
from rich.prompt import Confirm

from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..models import SemanticVersion

console = Console()


def _extract_version_from_text(text: str, debug: bool = False) -> Optional[str]:
    """
    Extract version string from text (issue title, PR title, etc).

    Looks for patterns like:
    - "Prepare Release 1.2.3"
    - "Release 1.2.3-rc.0"
    - "v1.2.3"

    Args:
        text: Text to search
        debug: Enable debug output

    Returns:
        Version string if found, None otherwise
    """
    if not text:
        return None

    import re
    # Pattern to match semantic versions (with optional 'v' prefix and prerelease)
    patterns = [
        r'v?(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.\d+)?)?)',  # Full version with optional prerelease
        r'v?(\d+\.\d+\.\d+)',  # Simple version
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            version = match.group(1)
            if debug:
                console.print(f"[dim]  Extracted version '{version}' from text: {text[:80]}...[/dim]")
            return version

    return None


def _find_pr_for_version(
    github_client: GitHubClient,
    db: Database,
    repo_full_name: str,
    version: str,
    issue_number: Optional[int] = None,
    debug: bool = False
) -> Tuple[Optional[int], Optional[str]]:
    """
    Find the PR number and branch associated with a version.

    Strategy:
    1. If issue_number provided, find PRs referencing that issue
    2. Search for PRs from release branches matching the version pattern
    3. Search for PRs with version in title

    Args:
        github_client: GitHub client instance
        db: Database instance
        repo_full_name: Full repository name
        version: Version string
        issue_number: Optional issue number to search for PRs
        debug: Enable debug output

    Returns:
        Tuple of (PR number, branch name) if found, (None, None) otherwise
    """
    pr_number = None
    branch_name = None

    if issue_number:
        # Strategy 1: Find PRs that reference this issue in their body
        if debug:
            console.print(f"[dim]    Strategy 1: Searching PRs that reference issue #{issue_number}...[/dim]")

        pr_numbers = github_client.find_prs_referencing_issue(
            repo_full_name,
            issue_number,
            state="open",
            quiet=True
        )

        if pr_numbers:
            pr_number = pr_numbers[0]
            if debug:
                console.print(f"[dim]    Found open PR: #{pr_number}[/dim]")

        # Also try closed PRs if no open ones found
        if not pr_number:
            pr_numbers = github_client.find_prs_referencing_issue(
                repo_full_name,
                issue_number,
                state="closed",
                quiet=True
            )
            if pr_numbers:
                pr_number = pr_numbers[0]
                if debug:
                    console.print(f"[dim]    Found closed PR: #{pr_number}[/dim]")

    # Strategy 2: Search for PRs by branch name or title
    if not pr_number:
        if debug:
            console.print(f"[dim]    Strategy 2: Searching PRs by branch/title...[/dim]")

        try:
            repo = github_client.gh.get_repo(repo_full_name)
            pulls = repo.get_pulls(state='all', sort='updated', direction='desc')

            for pr in pulls[:50]:  # Check up to 50 most recent PRs
                branch = pr.head.ref if pr.head else ""

                # Check if version appears in branch name or title
                if version in branch or version.replace('.', '') in branch.replace('.', ''):
                    pr_number = pr.number
                    branch_name = branch
                    if debug:
                        console.print(f"[dim]    ✓ Found PR #{pr_number} with branch: {branch}[/dim]")
                    break

                if version in pr.title:
                    pr_number = pr.number
                    branch_name = branch
                    if debug:
                        console.print(f"[dim]    ✓ Found PR #{pr_number} with matching title[/dim]")
                    break

        except Exception as e:
            if debug:
                console.print(f"[dim]    Warning: Error searching PRs: {e}[/dim]")

    # Get branch name if we have PR but no branch
    if pr_number and not branch_name:
        try:
            repo = github_client.gh.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            branch_name = pr.head.ref if pr.head else None
        except Exception as e:
            if debug:
                console.print(f"[dim]    Warning: Could not get branch name for PR #{pr_number}: {e}[/dim]")

    return pr_number, branch_name


def _resolve_version_pr_issue(
    config: Config,
    github_client: GitHubClient,
    db: Database,
    version: Optional[str],
    pr_number: Optional[int],
    issue_number: Optional[int],
    debug: bool
) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[int]]:
    """
    Resolve version, PR, branch, and issue from provided arguments with auto-detection.

    Args:
        config: Configuration object
        github_client: GitHub client instance
        db: Database instance
        version: Optional version
        pr_number: Optional PR number
        issue_number: Optional issue number
        debug: Enable debug output

    Returns:
        Tuple of (version, pr_number, branch_name, issue_number) or (None, None, None, None) if resolution fails
    """
    repo_full_name = config.repository.code_repo

    # Case 1: Issue number provided, try to get version from database
    if issue_number and not version:
        console.print(f"[cyan]Looking up version from issue #{issue_number}...[/cyan]")
        if debug:
            console.print(f"[dim]  Checking database for issue association...[/dim]")

        issue_assoc = db.get_issue_association_by_issue(repo_full_name, issue_number)
        if issue_assoc:
            version = issue_assoc['version']
            console.print(f"[green]  ✓ Found version {version} from database[/green]")
        else:
            if debug:
                console.print(f"[dim]  No database association found[/dim]")
                console.print(f"[dim]  Fetching issue from GitHub to parse title...[/dim]")

            # Try to extract from issue title
            try:
                repo = github_client.gh.get_repo(repo_full_name)
                issue = repo.get_issue(issue_number)
                version = _extract_version_from_text(issue.title, debug=debug)

                if version:
                    console.print(f"[green]  ✓ Extracted version {version} from issue title[/green]")
                else:
                    console.print(f"[red]Error: Could not extract version from issue #{issue_number}[/red]")
                    return None, None, None, None
            except Exception as e:
                console.print(f"[red]Error fetching issue #{issue_number}: {e}[/red]")
                return None, None, None, None

    # Ensure we have a version
    if not version:
        console.print("[red]Error: Could not determine version[/red]")
        console.print("[yellow]Please provide either:")
        console.print("  - A version number (e.g., 1.2.3)")
        console.print("  - An issue number with --issue[/yellow]")
        return None, None, None, None

    # Find PR and branch if not provided
    branch_name = None
    if not pr_number:
        console.print(f"\n[cyan]Looking for PR associated with version {version}...[/cyan]")

        # Get issue number if we have it
        if not issue_number:
            if debug:
                console.print(f"[dim]  Checking for issue association...[/dim]")
            issue_assoc = db.get_issue_association(repo_full_name, version)
            if issue_assoc:
                issue_number = issue_assoc.get('issue_number')
                if debug:
                    console.print(f"[dim]  Found issue #{issue_number}[/dim]")

        # Try to find PR
        pr_number, branch_name = _find_pr_for_version(
            github_client, db, repo_full_name, version, issue_number, debug=debug
        )

        if pr_number:
            console.print(f"[green]  ✓ Found PR #{pr_number}[/green]")
            if branch_name:
                console.print(f"[dim]    Branch: {branch_name}[/dim]")
        else:
            console.print(f"[yellow]  No PR found (will skip PR cleanup)[/yellow]")

    # Find issue if not provided
    if not issue_number:
        if debug:
            console.print(f"\n[dim]Looking for issue associated with version {version}...[/dim]")
        issue_assoc = db.get_issue_association(repo_full_name, version)
        if issue_assoc:
            issue_number = issue_assoc.get('issue_number')
            console.print(f"[green]  ✓ Found issue #{issue_number}[/green]")
        else:
            if debug:
                console.print(f"[dim]  No issue association found (will skip issue close)[/dim]")

    return version, pr_number, branch_name, issue_number


@click.command()
@click.argument('version', required=False)
@click.option('--issue', type=int, help='Issue number associated with release')
@click.option('--pr', type=int, help='PR number to close (auto-detected if not provided)')
@click.option('--force', is_flag=True, help='Allow canceling published releases')
@click.option('--dry-run', is_flag=True, help='Show what would be done without executing')
@click.pass_context
def cancel(ctx, version: Optional[str], issue: Optional[int], pr: Optional[int], force: bool, dry_run: bool):
    """
    Cancel a release by cleaning up all associated resources.

    This command will:
    1. Close the associated PR (if exists and not merged)
    2. Delete the PR branch (if exists)
    3. Delete the GitHub release
    4. Delete the git tag
    5. Delete database records
    6. Close the tracking issue (if exists)

    VERSION can be a version number (e.g., 1.2.3) or omitted if --issue is provided.

    SAFETY: By default, this command will NOT cancel published releases. Use --force to override.

    Examples:

        \b
        # Cancel by version
        release-tool cancel 1.2.3

        \b
        # Cancel from issue
        release-tool cancel --issue 42

        \b
        # Cancel published release (requires --force)
        release-tool cancel 1.2.3 --force

        \b
        # Dry-run to preview
        release-tool cancel 1.2.3 --dry-run
    """
    config: Config = ctx.obj['config']
    debug: bool = ctx.obj.get('debug', False)

    repo_full_name = config.repository.code_repo
    tag_prefix = config.version_policy.tag_prefix if hasattr(config, 'version_policy') else 'v'

    # Initialize clients
    github_client = GitHubClient(config)
    db = Database()
    db.connect()

    try:
        # Resolve version, PR, branch, and issue
        resolved_version, resolved_pr, resolved_branch, resolved_issue = _resolve_version_pr_issue(
            config, github_client, db, version, pr, issue, debug
        )

        if not resolved_version:
            sys.exit(1)

        # Check if release is published (safety check)
        tag_name = f"{tag_prefix}{resolved_version}" if not resolved_version.startswith(tag_prefix) else resolved_version

        try:
            release = github_client.get_release_by_tag(repo_full_name, tag_name)
            if release and not release.draft and not force:
                console.print(f"\n[red]✗ Cannot cancel published release {resolved_version}[/red]")
                console.print(f"[yellow]This release is already published and visible to users.[/yellow]")
                console.print(f"[yellow]Use --force to cancel it anyway (not recommended).[/yellow]")
                sys.exit(1)
        except Exception:
            # Release doesn't exist or error checking - continue
            pass

        console.print(f"\n[bold red]⚠️  Release Cancellation Plan for {resolved_version}[/bold red]")
        console.print(f"  Repository: {repo_full_name}")
        console.print(f"  Version: {resolved_version}")
        console.print(f"  PR: #{resolved_pr}" if resolved_pr else "  PR: None found")
        if resolved_branch:
            console.print(f"  Branch: {resolved_branch}")
        console.print(f"  Issue: #{resolved_issue}" if resolved_issue else "  Issue: None found")

        if dry_run:
            console.print("\n[yellow]DRY RUN - No changes will be made[/yellow]")

        console.print("\n[bold]Operations to perform:[/bold]")
        ops = []
        if resolved_pr:
            ops.append(f"  1. Close PR #{resolved_pr}")
        if resolved_branch:
            ops.append(f"  2. Delete branch '{resolved_branch}'")
        ops.append(f"  3. Delete GitHub release '{tag_name}'")
        ops.append(f"  4. Delete git tag '{tag_name}'")
        ops.append(f"  5. Delete database records")
        if resolved_issue:
            ops.append(f"  6. Close issue #{resolved_issue}")

        for op in ops:
            console.print(op)

        # Confirm in interactive mode
        if not dry_run and not ctx.obj.get('auto', False) and not ctx.obj.get('assume_yes', False):
            console.print()
            if not Confirm.ask("[bold yellow]Are you sure you want to cancel this release?[/bold yellow]", default=False):
                console.print("[yellow]Cancelled by user[/yellow]")
                sys.exit(0)

        # Execute cancellation operations (stop on first failure)
        console.print()

        # Step 1: Close PR if exists
        if resolved_pr:
            console.print(f"[bold cyan]Step 1: Closing PR #{resolved_pr}[/bold cyan]")
            if not dry_run:
                success = github_client.close_pull_request(
                    repo_full_name,
                    resolved_pr,
                    comment=f"Canceling release {resolved_version}."
                )
                if not success:
                    console.print(f"[red]✗ Failed to close PR #{resolved_pr}. Aborting.[/red]")
                    sys.exit(1)
            else:
                console.print(f"[dim]Would close PR #{resolved_pr}[/dim]")
        else:
            console.print("[dim]Step 1: No PR to close (skipping)[/dim]")

        # Step 2: Delete branch if exists
        if resolved_branch:
            console.print(f"\n[bold cyan]Step 2: Deleting branch '{resolved_branch}'[/bold cyan]")
            if not dry_run:
                success = github_client.delete_branch(repo_full_name, resolved_branch)
                if not success:
                    console.print(f"[red]✗ Failed to delete branch '{resolved_branch}'. Aborting.[/red]")
                    sys.exit(1)
            else:
                console.print(f"[dim]Would delete branch '{resolved_branch}'[/dim]")
        else:
            console.print("\n[dim]Step 2: No branch to delete (skipping)[/dim]")

        # Step 3: Delete GitHub release
        console.print(f"\n[bold cyan]Step 3: Deleting GitHub release '{tag_name}'[/bold cyan]")
        if not dry_run:
            success = github_client.delete_release(repo_full_name, tag_name)
            if not success:
                console.print(f"[red]✗ Failed to delete release. Aborting.[/red]")
                sys.exit(1)
        else:
            console.print(f"[dim]Would delete GitHub release '{tag_name}'[/dim]")

        # Step 4: Delete git tag
        console.print(f"\n[bold cyan]Step 4: Deleting git tag '{tag_name}'[/bold cyan]")
        if not dry_run:
            success = github_client.delete_tag(repo_full_name, tag_name)
            if not success:
                console.print(f"[red]✗ Failed to delete tag. Aborting.[/red]")
                sys.exit(1)
        else:
            console.print(f"[dim]Would delete git tag '{tag_name}'[/dim]")

        # Step 5: Delete database records
        console.print(f"\n[bold cyan]Step 5: Deleting database records[/bold cyan]")
        if not dry_run:
            try:
                # Delete release record
                db.cursor.execute(
                    """DELETE FROM releases
                       WHERE repo_id IN (SELECT id FROM repositories WHERE full_name=?)
                       AND version=?""",
                    (repo_full_name, resolved_version)
                )

                # Delete issue association
                db.cursor.execute(
                    """DELETE FROM release_issues
                       WHERE repo_full_name=? AND version=?""",
                    (repo_full_name, resolved_version)
                )

                db.conn.commit()
                console.print(f"[green]✓ Deleted database records for version {resolved_version}[/green]")
            except Exception as e:
                console.print(f"[red]✗ Failed to delete database records: {e}. Aborting.[/red]")
                sys.exit(1)
        else:
            console.print(f"[dim]Would delete database records for version {resolved_version}[/dim]")

        # Step 6: Close issue if exists
        if resolved_issue:
            console.print(f"\n[bold cyan]Step 6: Closing issue #{resolved_issue}[/bold cyan]")
            if not dry_run:
                success = github_client.close_issue(
                    repo_full_name,
                    resolved_issue,
                    comment=f"Release {resolved_version} has been cancelled."
                )
                if not success:
                    console.print(f"[red]✗ Failed to close issue #{resolved_issue}. Aborting.[/red]")
                    sys.exit(1)
            else:
                console.print(f"[dim]Would close issue #{resolved_issue}[/dim]")
        else:
            console.print("\n[dim]Step 6: No issue to close (skipping)[/dim]")

        # Success!
        console.print(f"\n[bold green]✓ Release {resolved_version} cancelled successfully![/bold green]")

        if dry_run:
            console.print("\n[yellow]This was a dry run. Use without --dry-run to execute.[/yellow]")

    except Exception as e:
        console.print(f"\n[red]Error: {str(e)}[/red]")
        if debug:
            import traceback
            console.print("\n[dim]Full traceback:[/dim]")
            console.print(traceback.format_exc())
        sys.exit(1)
    finally:
        db.close()
