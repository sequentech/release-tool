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


def _parse_ticket_key_arg(ticket_key_arg: str) -> tuple[Optional[str], Optional[str], bool]:
    """
    Parse smart TICKET_KEY argument into components.

    Supports multiple formats:
    - "1234" or "#1234" -> (None, "1234", False)
    - "meta#1234" -> ("meta", "1234", False)
    - "meta#1234~" -> ("meta", "1234", True)  # proximity search
    - "owner/repo#1234" -> ("owner/repo", "1234", False)
    - "owner/repo#1234~" -> ("owner/repo", "1234", True)

    Args:
        ticket_key_arg: The TICKET_KEY argument from CLI

    Returns:
        Tuple of (repo_filter, ticket_key, is_proximity)
        - repo_filter: Repository to filter by (None if not specified)
        - ticket_key: Ticket number/key
        - is_proximity: True if proximity search (~) was specified
    """
    # Check for proximity indicator (~)
    is_proximity = ticket_key_arg.endswith('~')
    if is_proximity:
        ticket_key_arg = ticket_key_arg[:-1]  # Remove trailing ~

    # Check if there's a # separator (indicating repo#ticket format)
    if '#' in ticket_key_arg:
        # Split on the last # to handle cases like "owner/repo#1234"
        parts = ticket_key_arg.rsplit('#', 1)
        if len(parts) == 2 and parts[1].isdigit():
            repo_part = parts[0] if parts[0] else None
            ticket_num = parts[1]
            return repo_part, ticket_num, is_proximity

    # No # separator, treat as plain ticket number (with optional leading #)
    match = re.match(r'^#?(\d+)$', ticket_key_arg)
    if match:
        return None, match.group(1), is_proximity

    # Invalid format, return as-is
    return None, ticket_key_arg, is_proximity


def _display_tickets_table(tickets: List, limit: int, offset: int):
    """Display tickets in a formatted table."""
    if not tickets:
        console.print("[yellow]No tickets found.[/yellow]")
        console.print("[dim]Tip: Run 'release-tool sync' to fetch latest tickets.[/dim]")
        return

    table = Table(title="Tickets" if offset == 0 else f"Tickets (offset: {offset})")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Repository", style="blue")
    table.add_column("Title")
    table.add_column("State", style="dim")
    table.add_column("URL", style="dim", max_width=80, overflow="fold")

    for ticket in tickets:
        # Get repo name (from bypassed Pydantic attribute or fallback)
        repo_name = getattr(ticket, '_repo_full_name', 'unknown')

        # Color code state
        state_style = "green" if ticket.state == "open" else "dim"
        state_text = f"[{state_style}]{ticket.state}[/{state_style}]"

        # Truncate title if too long
        title = ticket.title[:60] + "..." if len(ticket.title) > 60 else ticket.title

        # Don't truncate URL - let Rich handle it with max_width and overflow
        url = ticket.url if ticket.url else ""

        table.add_row(
            f"#{ticket.key}",
            repo_name,
            title,
            state_text,
            url
        )

    console.print(table)

    # Show pagination info
    total_shown = len(tickets)
    start_num = offset + 1
    end_num = offset + total_shown

    if total_shown == limit:
        console.print(f"\n[dim]Showing {start_num}-{end_num} tickets (use --offset to see more)[/dim]")
    else:
        console.print(f"\n[dim]Showing {start_num}-{end_num} tickets (all results)[/dim]")


def _display_tickets_csv(tickets: List):
    """Display tickets in CSV format."""
    if not tickets:
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

    for ticket in tickets:
        row = {
            'id': ticket.id,
            'repo_id': ticket.repo_id,
            'number': ticket.number,
            'key': ticket.key,
            'title': ticket.title,
            'body': ticket.body[:500] if ticket.body else "",  # Truncate long bodies
            'state': ticket.state,
            'labels': json.dumps([l.name for l in ticket.labels]),
            'url': ticket.url or "",
            'created_at': ticket.created_at.isoformat() if ticket.created_at else "",
            'closed_at': ticket.closed_at.isoformat() if ticket.closed_at else "",
            'category': ticket.category or "",
            'tags': json.dumps(ticket.tags),
            'repo_full_name': getattr(ticket, '_repo_full_name', '')
        }
        writer.writerow(row)

    # Print to stdout (user can redirect with >)
    print(output.getvalue(), end='')


@click.command(name='tickets', context_settings={'help_option_names': ['-h', '--help']})
@click.argument('ticket_key', required=False)
@click.option('--repo', '-r', help='Filter by repository (owner/name)')
@click.option('--limit', '-n', type=int, default=20, help='Max number of results (default: 20)')
@click.option('--offset', type=int, default=0, help='Skip first N results (for pagination)')
@click.option('--format', '-f', 'output_format', type=click.Choice(['table', 'csv']), default='table', help='Output format')
@click.option('--starts-with', help='Find tickets starting with prefix (fuzzy match)')
@click.option('--ends-with', help='Find tickets ending with suffix (fuzzy match)')
@click.option('--close-to', help='Find tickets numerically close to this number')
@click.option('--range', 'close_range', type=int, default=10, help='Range for --close-to (default: ±10)')
@click.pass_context
def tickets(ctx, ticket_key, repo, limit, offset, output_format, starts_with, ends_with, close_to, close_range):
    """Query tickets from local database (offline).

    IMPORTANT: This command works offline and only searches synced data.
    Run 'release-tool sync' first to ensure you have the latest tickets.

    TICKET_KEY supports smart formats:

      \b
      1234            Find ticket by number
      #1234           Find ticket by number (with # prefix)
      meta#1234       Find ticket 1234 in repo 'meta'
      meta#1234~      Find tickets close to 1234 (±20)
      owner/repo#1234 Find ticket in specific full repo path

    Examples:

      release-tool tickets 8624

      release-tool tickets meta#8624

      release-tool tickets meta#8624~

      release-tool tickets --repo sequentech/meta --limit 50

      release-tool tickets --starts-with 86

      release-tool tickets --ends-with 24

      release-tool tickets --close-to 8624 --range 50

      release-tool tickets --repo sequentech/meta --format csv > tickets.csv
    """
    config: Config = ctx.obj['config']

    # Parse smart TICKET_KEY format if provided
    parsed_repo = None
    parsed_ticket = None
    parsed_proximity = False

    if ticket_key:
        # Special case: if ticket_key looks like a repo name (contains "/" but no "#" or ticket number),
        # treat it as a --repo filter instead of a ticket key
        if '/' in ticket_key and '#' not in ticket_key and not any(c.isdigit() for c in ticket_key.split('/')[-1]):
            # This looks like "owner/repo" format, use as repo filter
            if not repo:
                repo = ticket_key
            ticket_key = None
        else:
            parsed_repo, parsed_ticket, parsed_proximity = _parse_ticket_key_arg(ticket_key)

            # If repo was parsed from ticket_key, use it (unless --repo was also specified)
            if parsed_repo and not repo:
                repo = parsed_repo

            # If proximity search (~) was indicated, use close_to
            if parsed_proximity and not close_to:
                close_to = parsed_ticket
                parsed_ticket = None  # Don't use as exact match

            # Use parsed ticket as the key
            ticket_key = parsed_ticket

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
        console.print("[red]Error: Database not found. Please run 'release-tool sync' first.[/red]")
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
            console.print("[yellow]Tip: Run 'release-tool sync' to fetch repository data.[/yellow]")
            sys.exit(1)
        repo_id = repo_obj.id

    # Query tickets
    try:
        tickets = db.query_tickets(
            ticket_key=ticket_key,
            repo_id=repo_id,
            starts_with=starts_with,
            ends_with=ends_with,
            close_to=close_to,
            close_range=close_range,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        console.print(f"[red]Error querying tickets: {e}[/red]")
        sys.exit(1)

    # Display results
    if output_format == 'table':
        _display_tickets_table(tickets, limit, offset)
    else:
        _display_tickets_csv(tickets)
