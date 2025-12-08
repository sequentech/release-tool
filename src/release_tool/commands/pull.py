# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

import click
from rich.console import Console
from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..pull_manager import PullManager

console = Console()

@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('repository', required=False)
@click.option('--repo-path', type=click.Path(exists=True), help='Path to local git repository')
@click.pass_context
def pull(ctx, repository, repo_path):
    """
    Pull repository data to local database.

    Fetches issues, PRs, releases, and commits from GitHub and stores them locally.
    Uses highly parallelized fetching with incremental pull.
    """
    # Get debug flag from global context
    debug = ctx.obj.get('debug', False)

    config: Config = ctx.obj['config']
    repo_name = repository or config.repository.code_repo

    if debug:
        console.print(f"[dim]Debug mode enabled[/dim]")
        console.print(f"[dim]Repository: {repo_name}[/dim]")
        console.print(f"[dim]Config path: {config.database.path}[/dim]")

    # Initialize components
    db = Database(config.database.path)
    db.connect()

    try:
        github_client = GitHubClient(config)
        pull_manager = PullManager(config, db, github_client)

        # Use the pull manager for parallelized, incremental pull
        console.print(f"[bold blue]Starting comprehensive pull...[/bold blue]")
        stats = pull_manager.pull_all()

        # Also fetch releases (not yet in PullManager)
        console.print("[blue]Fetching releases...[/blue]")
        repo_info = github_client.get_repository_info(repo_name)
        repo_id = db.upsert_repository(repo_info)
        releases = github_client.fetch_releases(repo_name, repo_id)
        for release in releases:
            db.upsert_release(release)
        console.print(f"[green]Pulled {len(releases)} releases[/green]")

        console.print("[bold green]Pull complete![/bold green]")
        console.print(f"[dim]Summary:[/dim]")
        console.print(f"  Issues: {stats['issues']}")
        console.print(f"  Pull Requests: {stats['pull_requests']}")
        console.print(f"  Releases: {len(releases)}")
        console.print(f"  Repositories: {', '.join(stats['repos_pulled'])}")
        if stats.get('git_repo_path'):
            console.print(f"  Git repo: {stats['git_repo_path']}")

    finally:
        db.close()
