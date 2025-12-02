import click
from rich.console import Console
from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..sync import SyncManager

console = Console()

@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('repository', required=False)
@click.option('--repo-path', type=click.Path(exists=True), help='Path to local git repository')
@click.pass_context
def sync(ctx, repository, repo_path):
    """
    Sync repository data to local database.

    Fetches tickets, PRs, releases, and commits from GitHub and stores them locally.
    Uses highly parallelized fetching with incremental sync.
    """
    config: Config = ctx.obj['config']
    repo_name = repository or config.repository.code_repo

    # Initialize components
    db = Database(config.database.path)
    db.connect()

    try:
        github_client = GitHubClient(config)
        sync_manager = SyncManager(config, db, github_client)

        # Use the new sync manager for parallelized, incremental sync
        console.print(f"[bold blue]Starting comprehensive sync...[/bold blue]")
        stats = sync_manager.sync_all()

        # Also fetch releases (not yet in SyncManager)
        console.print("[blue]Fetching releases...[/blue]")
        repo_info = github_client.get_repository_info(repo_name)
        repo_id = db.upsert_repository(repo_info)
        releases = github_client.fetch_releases(repo_name, repo_id)
        for release in releases:
            db.upsert_release(release)
        console.print(f"[green]Synced {len(releases)} releases[/green]")

        console.print("[bold green]Sync complete![/bold green]")
        console.print(f"[dim]Summary:[/dim]")
        console.print(f"  Tickets: {stats['tickets']}")
        console.print(f"  Pull Requests: {stats['pull_requests']}")
        console.print(f"  Releases: {len(releases)}")
        console.print(f"  Repositories: {', '.join(stats['repos_synced'])}")
        if stats.get('git_repo_path'):
            console.print(f"  Git repo: {stats['git_repo_path']}")

    finally:
        db.close()
