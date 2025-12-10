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
import re
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

    # Pattern to match semantic versions (with optional 'v' prefix and prerelease)
    # Matches: 1.2.3, v1.2.3, 1.2.3-rc.0, 1.2.3-beta.1, etc.
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
    issue_number: Optional[int] = None,
    debug: bool = False
) -> Optional[int]:
    """
    Find the PR number associated with a version.

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
        PR number if found, None otherwise
    """
    if issue_number:
        # Strategy 1: Find PRs that reference this issue in their body
        if debug:
            console.print(f"[dim]    Strategy 1: Searching PRs that reference issue #{issue_number} in body...[/dim]")

        pr_numbers = github_client.find_prs_referencing_issue(
            repo_full_name,
            issue_number,
            state="open",
            quiet=True  # Suppress console output, we'll handle logging
        )

        if pr_numbers:
            if debug:
                console.print(f"[dim]    Found open PR(s): {pr_numbers}[/dim]")
            return pr_numbers[0]

        # Also try closed PRs if no open ones found
        pr_numbers = github_client.find_prs_referencing_issue(
            repo_full_name,
            issue_number,
            state="closed",
            quiet=True  # Suppress console output, we'll handle logging
        )

        if pr_numbers:
            if debug:
                console.print(f"[dim]    Found closed PR(s): {pr_numbers}[/dim]")
            return pr_numbers[0]

    # Strategy 2: Search for PRs from release branches or with version in title
    if debug:
        console.print(f"[dim]    Strategy 2: Searching PRs by branch name or title...[/dim]")

    try:
        repo = github_client.gh.get_repo(repo_full_name)

        # Search open PRs
        pulls = repo.get_pulls(state='open', sort='updated', direction='desc')

        for pr in pulls[:50]:  # Check up to 50 most recent PRs
            # Check if branch name contains version
            # Common patterns: release/0.0, release/v0.0.1, docs/release-bot-14/release/0.0
            branch_name = pr.head.ref if pr.head else ""

            if debug and pr.number <= (pr.number if issue_number else 0) + 10:  # Show first few
                console.print(f"[dim]      Checking PR #{pr.number}: branch={branch_name}, title={pr.title[:50]}...[/dim]")

            # Check if version appears in branch name
            if version in branch_name or version.replace('.', '') in branch_name.replace('.', ''):
                if debug:
                    console.print(f"[dim]    ✓ Found PR #{pr.number} with matching branch: {branch_name}[/dim]")
                return pr.number

            # Check if version appears in PR title
            if version in pr.title:
                if debug:
                    console.print(f"[dim]    ✓ Found PR #{pr.number} with matching title: {pr.title}[/dim]")
                return pr.number

    except Exception as e:
        if debug:
            console.print(f"[dim]    Warning: Error searching PRs by branch/title: {e}[/dim]")

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
        console.print(f"[cyan]Looking up version from issue #{issue_number}...[/cyan]")
        if debug:
            console.print(f"[dim]  Step 1: Checking database for issue association...[/dim]")

        # Step 1: Look up version from issue association in database
        issue_assoc = db.get_issue_association_by_issue(repo_full_name, issue_number)
        if issue_assoc:
            version = issue_assoc['version']
            console.print(f"[green]  ✓ Found version {version} from database association[/green]")
            if debug:
                console.print(f"[dim]    Issue URL: {issue_assoc.get('issue_url', 'N/A')}[/dim]")
        else:
            if debug:
                console.print(f"[dim]  No database association found for issue #{issue_number}[/dim]")
                console.print(f"[dim]  Step 2: Fetching issue from GitHub to parse title...[/dim]")

            # Step 2: Fetch issue from GitHub and parse title
            try:
                repo = github_client.gh.get_repo(repo_full_name)
                issue = repo.get_issue(issue_number)
                issue_title = issue.title

                console.print(f"[cyan]  Issue title: {issue_title}[/cyan]")

                # Try to extract version from title
                version = _extract_version_from_text(issue_title, debug=debug)

                if version:
                    console.print(f"[green]  ✓ Extracted version {version} from issue title[/green]")
                else:
                    console.print(f"[red]Error: Could not extract version from issue #{issue_number}[/red]")
                    console.print(f"[yellow]Issue title: {issue_title}[/yellow]")
                    console.print(f"[yellow]Please ensure the issue title contains a version (e.g., 'Prepare Release 1.2.3')[/yellow]")
                    return None, None, None

            except Exception as e:
                console.print(f"[red]Error fetching issue #{issue_number}: {e}[/red]")
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
        console.print(f"\n[cyan]Looking for PR associated with version {version}...[/cyan]")

        # Get issue number if we have it
        if not issue_number:
            if debug:
                console.print(f"[dim]  Checking for issue association in database...[/dim]")
            issue_assoc = db.get_issue_association(repo_full_name, version)
            if issue_assoc:
                issue_number = issue_assoc.get('issue_number')
                if debug:
                    console.print(f"[dim]  Found issue #{issue_number} associated with version {version}[/dim]")

        # Try to find PR
        if issue_number:
            if debug:
                console.print(f"[dim]  Searching PRs that reference issue #{issue_number}...[/dim]")
        pr_number = _find_pr_for_version(github_client, db, repo_full_name, version, issue_number, debug=debug)

        if pr_number:
            console.print(f"[green]  ✓ Found PR #{pr_number}[/green]")
        else:
            console.print(f"[yellow]  No PR found (will skip merge step)[/yellow]")

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
                console.print(f"[dim]  No issue association found (will skip close step)[/dim]")

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
                # Fetch PR details to use for commit message
                try:
                    repo = github_client.gh.get_repo(repo_full_name)
                    pr = repo.get_pull(resolved_pr)
                    pr_title = pr.title
                    pr_body = pr.body or ""

                    if debug:
                        console.print(f"[dim]  PR title: {pr_title}[/dim]")
                        console.print(f"[dim]  PR body length: {len(pr_body)} chars[/dim]")

                    # Merge with PR title and body as commit message
                    success = github_client.merge_pull_request(
                        repo_full_name,
                        resolved_pr,
                        commit_title=pr_title,
                        commit_message=pr_body
                    )

                    if not success:
                        console.print(f"[red]Failed to merge PR #{resolved_pr}. Aborting.[/red]")
                        sys.exit(1)

                except Exception as e:
                    console.print(f"[red]Error fetching PR details: {e}[/red]")
                    sys.exit(1)
            else:
                console.print(f"[dim]Would merge PR #{resolved_pr} using PR title and body as commit message[/dim]")
        else:
            console.print("\n[dim]Step 1: No PR to merge (skipping)[/dim]")

        # Step 2: Publish release (mark draft as published)
        console.print(f"\n[bold cyan]Step 2: Publishing release {resolved_version}[/bold cyan]")
        if not dry_run:
            # Check if a GitHub release already exists
            try:
                # Construct tag name with proper prefix
                tag_prefix = config.version_policy.tag_prefix if hasattr(config, 'version_policy') else 'v'
                tag_name = f"{tag_prefix}{resolved_version}" if not resolved_version.startswith(tag_prefix) else resolved_version

                if debug:
                    console.print(f"[dim]  Checking for existing release with tag: {tag_name}[/dim]")

                existing_release = github_client.get_release_by_tag(repo_full_name, tag_name)

                if existing_release:
                    if existing_release.draft:
                        console.print(f"[cyan]  Found existing draft release, marking as published...[/cyan]")

                        # Mark release as published using direct GitHub API
                        release_url = github_client.update_release(
                            repo_full_name,
                            tag_name,
                            draft=False  # Mark as published
                        )

                        if release_url:
                            console.print(f"[green]✓ Release {resolved_version} marked as published[/green]")
                            if debug:
                                console.print(f"[dim]  URL: {release_url}[/dim]")
                        else:
                            raise Exception("Failed to update release")
                    else:
                        console.print(f"[green]  Release already published, skipping[/green]")
                else:
                    # No release exists - this is an error since merge should only finalize
                    console.print(f"[red]Error: No GitHub release found for {tag_name}[/red]")
                    console.print(f"[yellow]The merge command finalizes an existing release.[/yellow]")
                    console.print(f"[yellow]Please create the release first:[/yellow]")
                    console.print(f"[yellow]  1. Generate release notes: release-tool generate {resolved_version}[/yellow]")
                    console.print(f"[yellow]  2. Create draft release: release-tool push {resolved_version} --release-mode draft[/yellow]")
                    console.print(f"[yellow]  3. Then run merge again[/yellow]")
                    raise Exception("No release found to publish")

            except Exception as e:
                if "No release found" in str(e):
                    raise
                console.print(f"[red]Error checking/updating release: {e}[/red]")
                raise Exception(f"Failed to publish release: {e}")

        else:
            console.print(f"[dim]Would check for existing draft release and mark as published[/dim]")
            console.print(f"[dim]  - If draft exists: mark as published ✓[/dim]")
            console.print(f"[dim]  - If already published: skip (idempotent) ✓[/dim]")
            console.print(f"[dim]  - If no release: ERROR (must create first)[/dim]")

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

    except Exception as e:
        # Clean error handling - print user-friendly message and exit
        console.print(f"\n[red]Error: {str(e)}[/red]")
        if debug:
            import traceback
            console.print("\n[dim]Full traceback:[/dim]")
            console.print(traceback.format_exc())
        sys.exit(1)
    finally:
        db.close()
