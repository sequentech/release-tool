import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
import click
from rich.console import Console
from rich.table import Table

from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..models import SemanticVersion

console = Console()


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('version', required=False)
@click.option('--list', '-l', 'list_drafts', is_flag=True, help='List draft releases ready to be published')
@click.option('--notes-file', '-f', type=click.Path(exists=True), help='Path to release notes file (markdown)')
@click.option('--release/--no-release', 'create_release', default=None, help='Create GitHub release (default: from config)')
@click.option('--pr/--no-pr', 'create_pr', default=None, help='Create PR with release notes (default: from config)')
@click.option('--draft/--no-draft', 'draft', default=None, help='Create as draft release (default: from config)')
@click.option('--prerelease/--no-prerelease', 'prerelease', default=None, help='Mark as prerelease (default: from config, auto-detected from version)')
@click.option('--dry-run', is_flag=True, help='Show what would be published without making changes')
@click.option('--debug', is_flag=True, help='Show detailed debug information')
@click.pass_context
def publish(ctx, version: Optional[str], list_drafts: bool, notes_file: Optional[str], create_release: Optional[bool],
           create_pr: Optional[bool], draft: Optional[bool], prerelease: Optional[bool],
           dry_run: bool, debug: bool):
    """
    Publish a release to GitHub.

    Creates a GitHub release and/or pull request with release notes.
    Release notes can be read from a file or will be loaded from the database.

    Flags default to config values but can be overridden via CLI.

    Examples:

      release-tool publish 9.1.0 -f docs/releases/9.1.0.md

      release-tool publish 9.1.0-rc.0 --draft

      release-tool publish 9.1.0 --pr --no-release

      release-tool publish 9.1.0 -f notes.md --dry-run

      release-tool publish 9.1.0 -f notes.md --debug
    """
    config: Config = ctx.obj['config']

    if list_drafts:
        template = config.output.draft_output_path
        
        # Create a glob pattern that matches ALL repos
        # We replace {repo} with * to match any repository directory
        glob_pattern = template.replace("{repo}", "*")\
                               .replace("{version}", "*")\
                               .replace("{major}", "*")\
                               .replace("{minor}", "*")\
                               .replace("{patch}", "*")
        
        # Use glob on the current directory to find all matching files
        draft_files = list(Path('.').glob(glob_pattern))
        
        if not draft_files:
             console.print("[yellow]No draft releases found.[/yellow]")
             return
             
        # Sort by modification time desc
        draft_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        table = Table(title="Draft Releases")
        table.add_column("Code Repository", style="green")
        table.add_column("Version", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Created", style="magenta")
        table.add_column("Path", style="blue")
        
        for file_path in draft_files:
            # Extract repo name from parent directory (assuming default structure)
            # If the template structure is different, this might need adjustment
            repo_name = file_path.parent.name
            
            # Try to extract version from filename (assuming filename is version.md)
            version_str = file_path.stem
            try:
                version_obj = SemanticVersion.parse(version_str)
                rel_type = "RC" if not version_obj.is_final() else "Final"
            except ValueError:
                rel_type = "Unknown"
            
            # Get modification time
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            created_str = mtime.strftime("%Y-%m-%d %H:%M")
            
            table.add_row(
                repo_name,
                version_str,
                rel_type,
                created_str,
                str(file_path)
            )
            
        console.print(table)
        return

    if not version:
        console.print("[red]Error: Missing argument 'VERSION'.[/red]")
        console.print("\nUsage: release-tool publish [OPTIONS] VERSION")
        console.print("Try 'release-tool publish --help' for help.")
        sys.exit(1)

    try:
        # Use config defaults when CLI values are None
        create_release = create_release if create_release is not None else config.output.create_github_release
        create_pr = create_pr if create_pr is not None else config.output.create_pr
        draft = draft if draft is not None else config.output.draft_release
        prerelease_flag = prerelease if prerelease is not None else config.output.prerelease

        if debug:
            console.print("[dim]Debug: Configuration values:[/dim]")
            console.print(f"[dim]  create_release: {create_release} (CLI override: {prerelease is not None})[/dim]")
            console.print(f"[dim]  create_pr: {create_pr} (CLI override: {create_pr is not None})[/dim]")
            console.print(f"[dim]  draft: {draft} (CLI override: {draft is not None})[/dim]")
            console.print(f"[dim]  prerelease: {prerelease_flag} (CLI override: {prerelease is not None})[/dim]")

        # Parse version
        target_version = SemanticVersion.parse(version)

        if debug:
            console.print(f"[dim]Debug: Parsed version: {target_version.to_string()}[/dim]")
            console.print(f"[dim]  Major: {target_version.major}, Minor: {target_version.minor}, Patch: {target_version.patch}[/dim]")
            console.print(f"[dim]  Is final: {target_version.is_final()}[/dim]")

        # Auto-detect prerelease if not explicitly set and version is not final
        if not prerelease_flag and not target_version.is_final():
            prerelease_flag = True
            if debug or not dry_run:
                console.print(f"[blue]Auto-detected as prerelease version[/blue]")

        # Read release notes
        if notes_file:
            notes_path = Path(notes_file)
            release_notes = notes_path.read_text()
            if not dry_run or debug:
                console.print(f"[blue]Loaded release notes from {notes_file}[/blue]")
            if debug:
                console.print(f"[dim]Debug: Release notes length: {len(release_notes)} characters[/dim]")
        else:
            if not dry_run:
                console.print("[yellow]No notes file specified. Using version as release notes.[/yellow]")
            release_notes = f"# Release {version}\n\nRelease notes for version {version}."

        # Initialize GitHub client (only if not dry-run)
        github_client = None if dry_run else GitHubClient(config)
        repo_name = config.repository.code_repo

        if debug:
            console.print(f"[dim]Debug: Repository: {repo_name}[/dim]")
            console.print(f"[dim]Debug: Tag will be: v{version}[/dim]")

        # Dry-run banner
        if dry_run:
            console.print(f"\n[yellow]{'='*80}[/yellow]")
            console.print(f"[yellow]DRY RUN - Publish release {version}[/yellow]")
            console.print(f"[yellow]{'='*80}[/yellow]\n")

        # Create GitHub release
        if create_release:
            status = "draft " if draft else ("prerelease " if prerelease_flag else "")
            release_type = "draft" if draft else ("prerelease" if prerelease_flag else "final release")

            if dry_run:
                console.print(f"[yellow]Would create {status}GitHub release:[/yellow]")
                console.print(f"[yellow]  Repository: {repo_name}[/yellow]")
                console.print(f"[yellow]  Version: {version}[/yellow]")
                console.print(f"[yellow]  Tag: v{version}[/yellow]")
                console.print(f"[yellow]  Type: {release_type.capitalize()}[/yellow]")
                console.print(f"[yellow]  Status: {'Draft' if draft else 'Published'}[/yellow]")
                console.print(f"[yellow]  URL: https://github.com/{repo_name}/releases/tag/v{version}[/yellow]")

                # Show release notes preview
                preview_length = 500
                preview = release_notes[:preview_length]
                if len(release_notes) > preview_length:
                    preview += "\n[... truncated ...]"
                console.print(f"\n[yellow]Release notes preview ({len(release_notes)} characters):[/yellow]")
                console.print(f"[dim]{preview}[/dim]\n")
            else:
                console.print(f"[blue]Creating {status}GitHub release for {version}...[/blue]")

                release_name = f"Release {version}"
                github_client.create_release(
                    repo_name,
                    version,
                    release_name,
                    release_notes,
                    prerelease=prerelease_flag,
                    draft=draft
                )
                console.print(f"[green]✓ GitHub release created successfully[/green]")
                console.print(f"[blue]→ https://github.com/{repo_name}/releases/tag/v{version}[/blue]")
        elif dry_run:
            console.print(f"[yellow]Would NOT create GitHub release (--no-release or config setting)[/yellow]\n")

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

            if debug:
                console.print(f"[dim]Debug: PR template values:[/dim]")
                console.print(f"[dim]  Branch: {branch_name}[/dim]")
                console.print(f"[dim]  Title: {pr_title}[/dim]")
                console.print(f"[dim]  Target branch: {config.output.pr_target_branch}[/dim]")
                console.print(f"[dim]  Body preview: {pr_body[:100]}...[/dim]")

            if dry_run:
                console.print(f"[yellow]Would create pull request:[/yellow]")
                console.print(f"[yellow]  Branch: {branch_name}[/yellow]")
                console.print(f"[yellow]  Title: {pr_title}[/yellow]")
                console.print(f"[yellow]  Target: {config.output.pr_target_branch}[/yellow]")
                console.print(f"[yellow]  Notes file: {notes_file}[/yellow]")
                console.print(f"\n[yellow]PR body:[/yellow]")
                console.print(f"[dim]{pr_body}[/dim]\n")
            else:
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
        elif dry_run:
            console.print(f"[yellow]Would NOT create pull request (--no-pr or config setting)[/yellow]\n")

        # Handle Docusaurus file if configured
        if config.output.doc_output_path:
            doc_path = config.output.doc_output_path.format(
                version=version,
                major=str(target_version.major),
                minor=str(target_version.minor),
                patch=str(target_version.patch)
            )
            doc_file = Path(doc_path)

            if debug:
                console.print(f"[dim]Debug: Docusaurus path: {doc_path}[/dim]")
                console.print(f"[dim]Debug: File exists: {doc_file.exists()}[/dim]")

            if doc_file.exists():
                # Read doc file content for preview in debug mode
                doc_content = None
                if debug:
                    try:
                        doc_content = doc_file.read_text()
                        console.print(f"[dim]Debug: Docusaurus file length: {len(doc_content)} characters[/dim]")
                    except Exception as e:
                        console.print(f"[dim]Debug: Could not read doc file: {e}[/dim]")

                if dry_run:
                    console.print(f"[yellow]Docusaurus file: {doc_path}[/yellow]")
                    console.print(f"[yellow]  Status: File exists ({doc_file.stat().st_size} bytes)[/yellow]")
                    console.print(f"[yellow]  Note: You may want to commit this file to your repository[/yellow]")
                    console.print(f"[dim]  Example: git add {doc_path} && git commit -m \"Add release notes for {version}\"[/dim]")

                    # Show preview in debug mode
                    if debug and doc_content:
                        preview_length = 500
                        preview = doc_content[:preview_length]
                        if len(doc_content) > preview_length:
                            preview += "\n[... truncated ...]"
                        console.print(f"\n[yellow]Docusaurus notes preview ({len(doc_content)} characters):[/yellow]")
                        console.print(f"[dim]{preview}[/dim]\n")
                else:
                    console.print(f"[blue]Docusaurus file found at {doc_file}[/blue]")
                    console.print(f"[dim]Note: You may want to commit this file to your repository.[/dim]")
                    console.print(f"[dim]Example: git add {doc_path} && git commit -m \"Add release notes for {version}\"[/dim]")

                    # Show preview in debug mode (non-dry-run)
                    if debug and doc_content:
                        preview_length = 300
                        preview = doc_content[:preview_length]
                        if len(doc_content) > preview_length:
                            preview += "\n[... truncated ...]"
                        console.print(f"\n[dim]Debug: Docusaurus notes preview:[/dim]")
                        console.print(f"[dim]{preview}[/dim]\n")
            else:
                if dry_run or debug:
                    console.print(f"[dim]No Docusaurus file found at {doc_path}[/dim]")

        # Dry-run summary
        if dry_run:
            console.print(f"\n[yellow]{'='*80}[/yellow]")
            console.print(f"[yellow]DRY RUN complete. No changes were made.[/yellow]")
            console.print(f"[yellow]{'='*80}[/yellow]\n")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if debug:
            raise
        sys.exit(1)
