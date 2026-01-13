# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

import sys
from typing import Optional
import click
from rich.console import Console
from rich.table import Table
from datetime import datetime

from ..config import Config
from ..db import Database
from ..models import SemanticVersion

console = Console()


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('version', required=False)
@click.option('--repository', '-r', help='Filter by repository (owner/name)')
@click.option('--limit', '-n', type=int, default=10, help='Number of releases to show (default: 10, use 0 for all)')
@click.option('--type', '-t', multiple=True, type=click.Choice(['final', 'rc', 'beta', 'alpha'], case_sensitive=False), help='Release types to include (can be specified multiple times)')
@click.option('--after', type=str, help='Only show releases published after this date (YYYY-MM-DD)')
@click.option('--before', type=str, help='Only show releases published before this date (YYYY-MM-DD)')
@click.pass_context
def list_releases(ctx, version: Optional[str], repository: Optional[str], limit: int, type: tuple, after: Optional[str], before: Optional[str]):
    """
    List releases in the database.

    By default shows the last 10 releases. Use --limit 0 to show all releases.

    Examples:

      release-tool list-releases 9              # All 9.x.x releases

      release-tool list-releases 9.3            # All 9.3.x releases

      release-tool list-releases --type final               # Only final releases

      release-tool list-releases --type final --type rc     # Finals and RCs

      release-tool list-releases --after 2024-01-01         # Since 2024

      release-tool list-releases --before 2024-06-01        # Before June 2024
    """
    config: Config = ctx.obj['config']
    # Default to first code repo if no repository specified
    if not repository:
        if not config.repository.code_repos:
            console.print("[red]Error: No repository specified and no code repositories configured[/red]")
            sys.exit(1)
        repo_name = config.repository.code_repos[0].link
    else:
        repo_name = repository

    # Parse after date if provided
    after_date = None
    if after:
        try:
            after_date = datetime.fromisoformat(after)
        except ValueError:
            console.print(f"[red]Invalid date format for --after. Use YYYY-MM-DD[/red]")
            return

    # Parse before date if provided
    before_date = None
    if before:
        try:
            before_date = datetime.fromisoformat(before)
        except ValueError:
            console.print(f"[red]Invalid date format for --before. Use YYYY-MM-DD[/red]")
            return

    db = Database(config.database.path)
    db.connect()

    try:
        repo = db.get_repository(repo_name)
        if not repo:
            console.print(f"[red]Repository {repo_name} not found. Run 'pull' first.[/red]")
            return

        # Convert type tuple to list, default to all types if not specified
        release_types = list(type) if type else None

        # First get total count (without limit) to show "X out of Y"
        total_releases = db.get_all_releases(
            repo.id,
            limit=None,  # No limit for count
            version_prefix=version,
            release_types=release_types,
            after=after_date,
            before=before_date
        )
        total_count = len(total_releases)

        # Now get the limited results
        releases = db.get_all_releases(
            repo.id,
            limit=limit if limit > 0 else None,
            version_prefix=version,
            release_types=release_types,
            after=after_date,
            before=before_date
        )

        if not releases:
            console.print("[yellow]No releases found.[/yellow]")
            return

        # Build title with filter info
        title_parts = [f"Releases for {repo_name}"]
        if limit and limit > 0 and total_count > len(releases):
            title_parts.append(f"(showing {len(releases)} out of {total_count})")
        elif total_count > 0:
            title_parts.append(f"({total_count} total)")
        if version:
            title_parts.append(f"version {version}.x")
        if release_types:
            title_parts.append(f"types: {', '.join(release_types)}")
        if after:
            title_parts.append(f"after {after}")
        if before:
            title_parts.append(f"before {before}")

        table = Table(title=" ".join(title_parts))
        table.add_column("Version", style="cyan")
        table.add_column("Tag", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Published", style="magenta")
        table.add_column("URL", style="blue")

        for release in releases:
            version_obj = SemanticVersion.parse(release.version)
            rel_type = "RC" if not version_obj.is_final() else "Final"
            published = release.published_at.strftime("%Y-%m-%d") if release.published_at else "Draft"
            url = release.url if release.url else f"https://github.com/{repo_name}/releases/tag/{release.tag_name}"

            table.add_row(
                release.version,
                release.tag_name,
                rel_type,
                published,
                url
            )

        console.print(table)

    finally:
        db.close()
