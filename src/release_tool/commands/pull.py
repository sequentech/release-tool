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

    # If repository specified, use it; otherwise pull all configured code repos
    if repository:
        # Single repo mode (for backward compatibility or specific repo pull)
        repo_list = [repository]
    else:
        # Multi-repo mode - pull all configured code repos
        repo_list = [repo.link for repo in config.repository.code_repos]

    if debug:
        console.print(f"[dim]Debug mode enabled[/dim]")
        console.print(f"[dim]Repositories to pull: {', '.join(repo_list)}[/dim]")
        console.print(f"[dim]Config path: {config.database.path}[/dim]")

    # Initialize components
    db = Database(config.database.path)
    db.connect()

    try:
        github_client = GitHubClient(config)
        pull_manager = PullManager(config, db, github_client)

        # Use the pull manager for parallelized, incremental pull
        console.print(f"[bold blue]Starting comprehensive pull for {len(repo_list)} repository(ies)...[/bold blue]")
        stats = pull_manager.pull_all()

        # Also fetch releases for all code repos
        total_releases = 0
        console.print("[blue]Fetching releases from all code repos...[/blue]")
        for repo_name in repo_list:
            repo_info = github_client.get_repository_info(repo_name)
            repo_id = db.upsert_repository(repo_info)
            releases = github_client.fetch_releases(repo_name, repo_id)
            for release in releases:
                db.upsert_release(release)
            total_releases += len(releases)
            if debug:
                console.print(f"  [dim]Pulled {len(releases)} releases from {repo_name}[/dim]")

        console.print(f"[green]Pulled {total_releases} total releases[/green]")

        console.print("[bold green]Pull complete![/bold green]")
        console.print(f"[dim]Summary:[/dim]")
        console.print(f"  Issues: {stats['issues']}")
        console.print(f"  Pull Requests: {stats['pull_requests']}")
        console.print(f"  Releases: {total_releases}")
        console.print(f"  Repositories: {', '.join(stats['repos_pulled'])}")
        if stats.get('git_repo_paths'):
            console.print(f"  Git repos:")
            for repo_path in stats['git_repo_paths']:
                console.print(f"    {repo_path}")

    finally:
        db.close()
