import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console

from ..config import Config
from ..github_utils import GitHubClient
from ..models import SemanticVersion

console = Console()


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('version')
@click.option('--notes-file', '-f', type=click.Path(exists=True), help='Path to release notes file (markdown)')
@click.option('--release/--no-release', 'create_release', default=True, help='Create GitHub release (default: true)')
@click.option('--pr/--no-pr', 'create_pr', default=False, help='Create PR with release notes')
@click.option('--draft', is_flag=True, help='Create as draft release')
@click.option('--prerelease', is_flag=True, help='Mark as prerelease (auto-detected from version if not specified)')
@click.pass_context
def publish(ctx, version: str, notes_file: Optional[str], create_release: bool,
           create_pr: bool, draft: bool, prerelease: bool):
    """
    Publish a release to GitHub.

    Creates a GitHub release and/or pull request with release notes.
    Release notes can be read from a file or will be loaded from the database.

    Examples:
      release-tool publish 9.1.0 -f docs/releases/9.1.0.md
      release-tool publish 9.1.0-rc.0 --draft
      release-tool publish 9.1.0 --pr --no-release
    """
    config: Config = ctx.obj['config']

    try:
        # Parse version
        target_version = SemanticVersion.parse(version)

        # Auto-detect prerelease if not explicitly set
        if not prerelease and not target_version.is_final():
            prerelease = True
            console.print(f"[blue]Auto-detected as prerelease version[/blue]")

        # Read release notes
        if notes_file:
            notes_path = Path(notes_file)
            release_notes = notes_path.read_text()
            console.print(f"[blue]Loaded release notes from {notes_file}[/blue]")
        else:
            console.print("[yellow]No notes file specified. Using version as release notes.[/yellow]")
            release_notes = f"# Release {version}\n\nRelease notes for version {version}."

        # Initialize GitHub client
        github_client = GitHubClient(config)
        repo_name = config.repository.code_repo

        # Create GitHub release
        if create_release:
            status = "draft " if draft else ("prerelease " if prerelease else "")
            console.print(f"[blue]Creating {status}GitHub release for {version}...[/blue]")

            release_name = f"Release {version}"
            github_client.create_release(
                repo_name,
                version,
                release_name,
                release_notes,
                prerelease=prerelease,
                draft=draft
            )
            console.print(f"[green]✓ GitHub release created successfully[/green]")
            console.print(f"[blue]→ https://github.com/{repo_name}/releases/tag/v{version}[/blue]")

        # Create PR
        if create_pr:
            if not notes_file:
                console.print("[red]Error: --notes-file required when creating PR[/red]")
                return

            # Format PR templates
            version_parts = {
                'version': version,
                'major': str(target_version.major),
                'minor': str(target_version.minor),
                'patch': str(target_version.patch)
            }

            branch_name = config.output.pr_templates.branch_template.format(**version_parts)
            pr_title = config.output.pr_templates.title_template.format(**version_parts)
            pr_body = config.output.pr_templates.body_template.format(**version_parts)

            console.print(f"[blue]Creating PR with release notes...[/blue]")
            github_client.create_pr_for_release_notes(
                repo_name,
                pr_title,
                notes_file,
                release_notes,
                branch_name,
                config.output.pr_target_branch,
                pr_body
            )
            console.print(f"[green]✓ Pull request created successfully[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if '--debug' in sys.argv:
            raise
        sys.exit(1)
