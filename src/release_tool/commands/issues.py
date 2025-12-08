# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path
from typing import List, Optional
import click
from rich.console import Console
from rich.table import Table
import csv
import json
from io import StringIO
import re

from ..config import Config
from ..db import Database

console = Console()


def _parse_issue_key_arg(issue_key_arg: str) -> tuple[Optional[str], Optional[str], bool]:
    """
    Parse smart ISSUE_KEY argument into components.

    Supports multiple formats:
    - "1234" or "#1234" -> (None, "1234", False)
    - "meta#1234" -> ("meta", "1234", False)
    - "meta#1234~" -> ("meta", "1234", True)  # proximity search
    - "owner/repo#1234" -> ("owner/repo", "1234", False)
    - "owner/repo#1234~" -> ("owner/repo", "1234", True)

    Args:
        issue_key_arg: The ISSUE_KEY argument from CLI

    Returns:
        Tuple of (repo_filter, issue_key, is_proximity)
        - repo_filter: Repository to filter by (None if not specified)
        - issue_key: Issue number/key
        - is_proximity: True if proximity search (~) was specified
    """
    # Check for proximity indicator (~)
    is_proximity = issue_key_arg.endswith('~')
    if is_proximity:
        issue_key_arg = issue_key_arg[:-1]  # Remove trailing ~

    # Check if there's a # separator (indicating repo#issue format)
    if '#' in issue_key_arg:
        # Split on the last # to handle cases like "owner/repo#1234"
        parts = issue_key_arg.rsplit('#', 1)
        if len(parts) == 2 and parts[1].isdigit():
            repo_part = parts[0] if parts[0] else None
            issue_num = parts[1]
            return repo_part, issue_num, is_proximity

    # No # separator, treat as plain issue number (with optional leading #)
    match = re.match(r'^#?(\d+)$', issue_key_arg)
    if match:
        return None, match.group(1), is_proximity

    # Invalid format, return as-is
    return None, issue_key_arg, is_proximity


def _display_issues_table(issues: List, limit: int, offset: int):
    """Display issues in a formatted table."""
    if not issues:
        console.print("[yellow]No issues found.[/yellow]")
        console.print("[dim]Tip: Run 'release-tool pull' to fetch latest issues.[/dim]")
        return

    table = Table(title="Issues" if offset == 0 else f"Issues (offset: {offset})")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Repository", style="blue")
    table.add_column("Title")
    table.add_column("State", style="dim")
    table.add_column("URL", style="dim", max_width=80, overflow="fold")

    for issue in issues:
        # Get repo name (from bypassed Pydantic attribute or fallback)
        repo_name = getattr(issue, '_repo_full_name', 'unknown')

        # Color code state
        state_style = "green" if issue.state == "open" else "dim"
        state_text = f"[{state_style}]{issue.state}[/{state_style}]"

        # Truncate title if too long
        title = issue.title[:60] + "..." if len(issue.title) > 60 else issue.title

        # Don't truncate URL - let Rich handle it with max_width and overflow
        url = issue.url if issue.url else ""

        table.add_row(
            f"#{issue.key}",
            repo_name,
            title,
            state_text,
            url
        )

    console.print(table)

    # Show pagination info
    total_shown = len(issues)
    start_num = offset + 1
    end_num = offset + total_shown

    if total_shown == limit:
        console.print(f"\n[dim]Showing {start_num}-{end_num} issues (use --offset to see more)[/dim]")
    else:
        console.print(f"\n[dim]Showing {start_num}-{end_num} issues (all results)[/dim]")


def _display_issues_csv(issues: List):
    """Display issues in CSV format."""
    if not issues:
        return

    # Use StringIO to build CSV, then print
    output = StringIO()

    # Define all fields to export
    fieldnames = [
        'id', 'repo_id', 'number', 'key', 'title', 'body', 'state',
        'labels', 'url', 'created_at', 'closed_at', 'category', 'tags',
        'repo_full_name'
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()

    for issue in issues:
        row = {
            'id': issue.id,
            'repo_id': issue.repo_id,
            'number': issue.number,
            'key': issue.key,
            'title': issue.title,
            'body': issue.body[:500] if issue.body else "",  # Truncate long bodies
            'state': issue.state,
            'labels': json.dumps([l.name for l in issue.labels]),
            'url': issue.url or "",
            'created_at': issue.created_at.isoformat() if issue.created_at else "",
            'closed_at': issue.closed_at.isoformat() if issue.closed_at else "",
            'category': issue.category or "",
            'tags': json.dumps(issue.tags),
            'repo_full_name': getattr(issue, '_repo_full_name', '')
        }
        writer.writerow(row)

    # Print to stdout (user can redirect with >)
    print(output.getvalue(), end='')


@click.command(name='issues', context_settings={'help_option_names': ['-h', '--help']})
@click.argument('issue_key', required=False)
@click.option('--repo', '-r', help='Filter by repository (owner/name)')
@click.option('--limit', '-n', type=int, default=20, help='Max number of results (default: 20)')
@click.option('--offset', type=int, default=0, help='Skip first N results (for pagination)')
@click.option('--format', '-f', 'output_format', type=click.Choice(['table', 'csv']), default='table', help='Output format')
@click.option('--starts-with', help='Find issues starting with prefix (fuzzy match)')
@click.option('--ends-with', help='Find issues ending with suffix (fuzzy match)')
@click.option('--close-to', help='Find issues numerically close to this number')
@click.option('--range', 'close_range', type=int, default=10, help='Range for --close-to (default: ±10)')
@click.pass_context
def issues(ctx, issue_key, repo, limit, offset, output_format, starts_with, ends_with, close_to, close_range):
    """Query issues from local database (offline).

    IMPORTANT: This command works offline and only searches pulled data.
    Run 'release-tool pull' first to ensure you have the latest issues.

    ISSUE_KEY supports smart formats:

      \b
      1234            Find issue by number
      #1234           Find issue by number (with # prefix)
      meta#1234       Find issue 1234 in repo 'meta'
      meta#1234~      Find issues close to 1234 (±20)
      owner/repo#1234 Find issue in specific full repo path

    Examples:

      release-tool issues 8624

      release-tool issues meta#8624

      release-tool issues meta#8624~

      release-tool issues --repo sequentech/meta --limit 50

      release-tool issues --starts-with 86

      release-tool issues --ends-with 24

      release-tool issues --close-to 8624 --range 50

      release-tool issues --repo sequentech/meta --format csv > issues.csv
    """
    config: Config = ctx.obj['config']

    # Parse smart ISSUE_KEY format if provided
    parsed_repo = None
    parsed_issue = None
    parsed_proximity = False

    if issue_key:
        # Special case: if issue_key looks like a repo name (contains "/" but no "#" or issue number),
        # treat it as a --repo filter instead of a issue key
        if '/' in issue_key and '#' not in issue_key and not any(c.isdigit() for c in issue_key.split('/')[-1]):
            # This looks like "owner/repo" format, use as repo filter
            if not repo:
                repo = issue_key
            issue_key = None
        else:
            parsed_repo, parsed_issue, parsed_proximity = _parse_issue_key_arg(issue_key)

            # If repo was parsed from issue_key, use it (unless --repo was also specified)
            if parsed_repo and not repo:
                repo = parsed_repo

            # If proximity search (~) was indicated, use close_to
            if parsed_proximity and not close_to:
                close_to = parsed_issue
                parsed_issue = None  # Don't use as exact match

            # Use parsed issue as the key
            issue_key = parsed_issue

    # Validation
    if close_range < 0:
        console.print("[red]Error: --range must be >= 0[/red]")
        sys.exit(1)

    if limit <= 0:
        console.print("[red]Error: --limit must be > 0[/red]")
        sys.exit(1)

    if offset < 0:
        console.print("[red]Error: --offset must be >= 0[/red]")
        sys.exit(1)

    # Cannot combine close_to with starts_with or ends_with
    if close_to and (starts_with or ends_with):
        console.print("[red]Error: Cannot combine --close-to with --starts-with or --ends-with[/red]")
        sys.exit(1)

    # Open database
    db_path = Path(config.database.path)
    if not db_path.exists():
        console.print("[red]Error: Database not found. Please run 'release-tool pull' first.[/red]")
        sys.exit(1)

    db = Database(str(db_path))
    db.connect()

    # Convert repo name to repo_id if needed
    repo_id = None
    if repo:
        # Try as full name first
        repo_obj = db.get_repository(repo)

        # If not found and repo doesn't contain '/', try finding by name only
        if not repo_obj and '/' not in repo:
            # Search for repos matching this name
            all_repos = db.get_all_repositories()
            matching = [r for r in all_repos if r.name == repo]
            if len(matching) == 1:
                repo_obj = matching[0]
            elif len(matching) > 1:
                console.print(f"[red]Error: Multiple repositories match '{repo}'. Please specify as owner/repo:[/red]")
                for r in matching:
                    console.print(f"  - {r.full_name}")
                sys.exit(1)

        if not repo_obj:
            console.print(f"[red]Error: Repository '{repo}' not found in database.[/red]")
            console.print("[yellow]Tip: Run 'release-tool pull' to fetch repository data.[/yellow]")
            sys.exit(1)
        repo_id = repo_obj.id

    # Query issues
    try:
        issues = db.query_issues(
            issue_key=issue_key,
            repo_id=repo_id,
            starts_with=starts_with,
            ends_with=ends_with,
            close_to=close_to,
            close_range=close_range,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        console.print(f"[red]Error querying issues: {e}[/red]")
        sys.exit(1)

    # Display results
    if output_format == 'table':
        _display_issues_table(issues, limit, offset)
    else:
        _display_issues_csv(issues)
