# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Merge command for release-tool.

This command automates the final steps of the release process by:
1. Merging the associated PR (if not already merged)
2. Marking the release as published (from draft to published)
3. Closing the related issue (if not already closed)
"""

import sys
from typing import Optional, List, Dict, Tuple
from pathlib import Path
import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..models import SemanticVersion

console = Console()


def _find_matching_versions(
    db: Database,
    repo_full_name: str,
    partial_version: str,
    require_pr_or_issue: bool = True
) -> List[str]:
    """
    Find full versions that match a partial version string.

    Args:
        db: Database instance
        repo_full_name: Full repository name
        partial_version: Partial version like "1.2" or "1.2.3"
        require_pr_or_issue: If True, only return versions with associated PR or issue

    Returns:
        List of matching full version strings
    """
    # Get all releases from database
    all_releases = db.get_all_releases(repo_full_name)

    matching = []
    for release in all_releases:
        version = release['version']

        # Check if this version matches the partial string
        if version.startswith(partial_version):
            if require_pr_or_issue:
                # Check if there's an associated issue or PR
                issue_assoc = db.get_issue_association(repo_full_name, version)
                if issue_assoc:
                    matching.append(version)
            else:
                matching.append(version)

    return matching


def _find_pr_for_version(
    github_client: GitHubClient,
    db: Database,
    repo_full_name: str,
    version: str,
    issue_number: Optional[int] = None
) -> Optional[int]:
    """
    Find the PR number associated with a version.

    Strategy:
    1. If issue_number provided, find PRs referencing that issue
    2. Otherwise, look for open PRs from release branches matching the version

    Args:
        github_client: GitHub client instance
        db: Database instance
        repo_full_name: Full repository name
        version: Version string
        issue_number: Optional issue number to search for PRs

    Returns:
        PR number if found, None otherwise
    """
    if issue_number:
        # Find PRs that reference this issue
        pr_numbers = github_client.find_prs_referencing_issue(
            repo_full_name,
            issue_number,
            state="open"
        )

        if pr_numbers:
            # Return the first one (most recently updated)
            return pr_numbers[0]

        # Also try closed PRs if no open ones found
        pr_numbers = github_client.find_prs_referencing_issue(
            repo_full_name,
            issue_number,
            state="closed"
        )

        if pr_numbers:
            return pr_numbers[0]

    # TODO: Could also search for PRs from release branches matching version
    # This would require parsing branch names from the config's release_branch_template

    return None


def _select_from_matches(
    matches: List[Dict],
    auto_mode: bool,
    item_type: str = "version"
) -> Optional[Dict]:
    """
    Select an item from a list of matches.

    Args:
        matches: List of match dictionaries
        auto_mode: If True, automatically select first match
        item_type: Type of item being selected (for display)

    Returns:
        Selected match or None if cancelled
    """
    if not matches:
        return None

    if len(matches) == 1:
        return matches[0]

    if auto_mode:
        console.print(f"[yellow]Multiple {item_type}s found, using first match (--auto mode)[/yellow]")
        return matches[0]

    # Show matches
    console.print(f"\n[cyan]Multiple {item_type}s found:[/cyan]")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Version", style="cyan")
    table.add_column("Issue", style="yellow")
    table.add_column("PR", style="green")

    display_matches = matches[:5]  # Show first 5
    for idx, match in enumerate(display_matches, 1):
        table.add_row(
            str(idx),
            match.get('version', 'N/A'),
            str(match.get('issue', 'N/A')),
            str(match.get('pr', 'N/A'))
        )

    if len(matches) > 5:
        console.print(f"[dim](Showing first 5 of {len(matches)} matches)[/dim]")

    console.print(table)

    # Prompt for selection
    choice = Prompt.ask(
        "\nSelect a number (or 'c' to cancel)",
        choices=[str(i) for i in range(1, len(display_matches) + 1)] + ['c'],
        default='c'
    )

    if choice == 'c':
        console.print("[yellow]Cancelled by user[/yellow]")
        return None

    return display_matches[int(choice) - 1]


def _resolve_version_pr_issue(
    config: Config,
    github_client: GitHubClient,
    db: Database,
    version: Optional[str],
    pr_number: Optional[int],
    issue_number: Optional[int],
    auto_mode: bool,
    debug: bool
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Resolve version, PR, and issue from provided arguments with auto-detection.

    Args:
        config: Configuration object
        github_client: GitHub client instance
        db: Database instance
        version: Optional version (can be partial)
        pr_number: Optional PR number
        issue_number: Optional issue number
        auto_mode: If True, auto-select when multiple matches
        debug: Enable debug output

    Returns:
        Tuple of (version, pr_number, issue_number) or (None, None, None) if resolution fails
    """
    repo_full_name = config.repository.code_repo

    # Case 1: Issue number provided
    if issue_number and not version:
        if debug:
            console.print(f"[dim]Looking up version from issue #{issue_number}...[/dim]")

        # Look up version from issue association
        issue_assoc = db.get_issue_association_by_issue(repo_full_name, issue_number)
        if issue_assoc:
            version = issue_assoc['version']
            if debug:
                console.print(f"[dim]Found version {version} associated with issue #{issue_number}[/dim]")
        else:
            console.print(f"[red]Error: No version found associated with issue #{issue_number}[/red]")
            return None, None, None

    # Case 2: Partial version provided
    if version:
        # Check if version is complete (has major.minor.patch format)
        parts = version.split('.')
        if len(parts) < 3:
            if debug:
                console.print(f"[dim]Partial version '{version}' detected, searching for matches...[/dim]")

            # Find matching full versions
            matches = _find_matching_versions(db, repo_full_name, version, require_pr_or_issue=True)

            if not matches:
                console.print(f"[red]Error: No matching versions found for '{version}' with associated PR or issue[/red]")
                return None, None, None

            if len(matches) > 1:
                # Build match dictionaries with PR and issue info
                match_dicts = []
                for v in matches:
                    issue_assoc = db.get_issue_association(repo_full_name, v)
                    pr_num = None
                    issue_num = None

                    if issue_assoc:
                        issue_num = issue_assoc.get('issue_number')
                        # Try to find PR for this version
                        pr_num = _find_pr_for_version(github_client, db, repo_full_name, v, issue_num)

                    match_dicts.append({
                        'version': v,
                        'issue': issue_num,
                        'pr': pr_num
                    })

                # Let user select or auto-select
                selected = _select_from_matches(match_dicts, auto_mode, "version")
                if not selected:
                    return None, None, None

                version = selected['version']
                if not pr_number:
                    pr_number = selected.get('pr')
                if not issue_number:
                    issue_number = selected.get('issue')
            else:
                version = matches[0]
                if debug:
                    console.print(f"[dim]Resolved to full version: {version}[/dim]")

    # Ensure we have a version at this point
    if not version:
        console.print("[red]Error: Could not determine version[/red]")
        console.print("[yellow]Please provide either:")
        console.print("  - A version number (e.g., 1.2.3 or 1.2)")
        console.print("  - An issue number with --issue[/yellow]")
        return None, None, None

    # Find PR if not provided
    if not pr_number:
        if debug:
            console.print(f"[dim]Looking for PR associated with version {version}...[/dim]")

        # Get issue number if we have it
        if not issue_number:
            issue_assoc = db.get_issue_association(repo_full_name, version)
            if issue_assoc:
                issue_number = issue_assoc.get('issue_number')

        # Try to find PR
        pr_number = _find_pr_for_version(github_client, db, repo_full_name, version, issue_number)

        if pr_number and debug:
            console.print(f"[dim]Found PR #{pr_number} for version {version}[/dim]")

    # Find issue if not provided
    if not issue_number:
        issue_assoc = db.get_issue_association(repo_full_name, version)
        if issue_assoc:
            issue_number = issue_assoc.get('issue_number')
            if debug:
                console.print(f"[dim]Found issue #{issue_number} for version {version}[/dim]")

    return version, pr_number, issue_number


@click.command()
@click.argument('version', required=False)
@click.option('--issue', type=int, help='Issue number to associate with release')
@click.option('--pr', type=int, help='PR number to merge (auto-detected if not provided)')
@click.option('--dry-run', is_flag=True, help='Show what would be done without executing')
@click.pass_context
def merge(ctx, version: Optional[str], issue: Optional[int], pr: Optional[int], dry_run: bool):
    """
    Merge a release by:
    1. Merging the associated PR (if not already merged)
    2. Marking the release as published (from draft to published)
    3. Closing the related issue (if not already closed)

    VERSION can be a full version (1.2.3) or partial (1.2) to auto-detect.

    Examples:

        \b
        # Auto-detect everything from issue
        release-tool merge --issue 42

        \b
        # Specify full version
        release-tool merge 1.2.3 --issue 42

        \b
        # Specify partial version, auto-detect full version
        release-tool merge 1.2 --issue 42

        \b
        # Dry-run to preview actions
        release-tool merge 1.2.3 --issue 42 --dry-run

        \b
        # Explicitly specify PR number
        release-tool merge 1.2.3 --pr 123 --issue 42
    """
    config: Config = ctx.obj['config']
    debug: bool = ctx.obj.get('debug', False)
    auto_mode: bool = ctx.obj.get('auto', False) or ctx.obj.get('assume_yes', False)

    repo_full_name = config.repository.code_repo

    # Initialize clients
    github_client = GitHubClient(config)
    db = Database()
    db.connect()

    try:
        # Resolve version, PR, and issue
        resolved_version, resolved_pr, resolved_issue = _resolve_version_pr_issue(
            config, github_client, db, version, pr, issue, auto_mode, debug
        )

        if not resolved_version:
            sys.exit(1)

        console.print(f"\n[bold cyan]Release Merge Plan for {resolved_version}[/bold cyan]")
        console.print(f"  Repository: {repo_full_name}")
        console.print(f"  Version: {resolved_version}")
        console.print(f"  PR: #{resolved_pr}" if resolved_pr else "  PR: None found")
        console.print(f"  Issue: #{resolved_issue}" if resolved_issue else "  Issue: None found")

        if dry_run:
            console.print("\n[yellow]DRY RUN - No changes will be made[/yellow]")

        console.print("\n[bold]Steps to execute:[/bold]")
        console.print("  1. Merge PR (if exists and not merged)")
        console.print("  2. Mark release as published")
        console.print("  3. Close issue (if exists and not closed)")

        # Step 1: Merge PR
        if resolved_pr:
            console.print(f"\n[bold cyan]Step 1: Merging PR #{resolved_pr}[/bold cyan]")
            if not dry_run:
                success = github_client.merge_pull_request(repo_full_name, resolved_pr)
                if not success:
                    console.print(f"[red]Failed to merge PR #{resolved_pr}. Aborting.[/red]")
                    sys.exit(1)
            else:
                console.print(f"[dim]Would merge PR #{resolved_pr}[/dim]")
        else:
            console.print("\n[dim]Step 1: No PR to merge (skipping)[/dim]")

        # Step 2: Mark release as published
        console.print(f"\n[bold cyan]Step 2: Marking release {resolved_version} as published[/bold cyan]")
        if not dry_run:
            # Use push command with mark-published mode
            from release_tool.commands.push import push
            from click.testing import CliRunner

            runner = CliRunner()
            push_args = [resolved_version, '--release-mode', 'mark-published']
            if resolved_issue:
                push_args.extend(['--issue', str(resolved_issue)])
            if debug:
                push_args.append('--debug')

            # Invoke push command programmatically
            result = runner.invoke(push, push_args, obj=ctx.obj)

            if result.exit_code != 0:
                console.print(f"[red]Failed to mark release as published. Exit code: {result.exit_code}[/red]")
                if result.output:
                    console.print(f"[red]{result.output}[/red]")
                sys.exit(1)
            else:
                console.print(f"[green]✓ Release {resolved_version} marked as published[/green]")
        else:
            console.print(f"[dim]Would mark release {resolved_version} as published using:[/dim]")
            console.print(f"[dim]  release-tool push {resolved_version} --release-mode mark-published[/dim]")

        # Step 3: Close issue
        if resolved_issue:
            console.print(f"\n[bold cyan]Step 3: Closing issue #{resolved_issue}[/bold cyan]")
            if not dry_run:
                success = github_client.close_issue(
                    repo_full_name,
                    resolved_issue,
                    comment=f"Release {resolved_version} has been published."
                )
                if not success:
                    console.print(f"[yellow]Warning: Failed to close issue #{resolved_issue}[/yellow]")
                    # Don't exit on issue close failure - release is already published
            else:
                console.print(f"[dim]Would close issue #{resolved_issue}[/dim]")
        else:
            console.print("\n[dim]Step 3: No issue to close (skipping)[/dim]")

        # Success!
        console.print(f"\n[bold green]✓ Release {resolved_version} merge complete![/bold green]")

        if dry_run:
            console.print("\n[yellow]This was a dry run. Use without --dry-run to execute.[/yellow]")

    finally:
        db.close()
