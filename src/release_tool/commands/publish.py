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


def _find_draft_releases(config: Config, version_filter: Optional[str] = None) -> list[Path]:
    """
    Find draft release files matching the configured path template.

    Args:
        config: Configuration object
        version_filter: Optional version string to filter results (e.g., "9.2.0")

    Returns:
        List of Path objects for draft release files, sorted by modification time (newest first)
    """
    template = config.output.draft_output_path

    # Create a glob pattern that matches ALL repos and versions
    # We replace placeholders with * to match any value
    if version_filter:
        # If filtering by version, keep the version in the pattern
        glob_pattern = template.replace("{repo}", "*")\
                               .replace("{version}", version_filter)\
                               .replace("{major}", "*")\
                               .replace("{minor}", "*")\
                               .replace("{patch}", "*")
    else:
        # Match all versions
        glob_pattern = template.replace("{repo}", "*")\
                               .replace("{version}", "*")\
                               .replace("{major}", "*")\
                               .replace("{minor}", "*")\
                               .replace("{patch}", "*")

    # Use glob on the current directory to find all matching files
    draft_files = list(Path('.').glob(glob_pattern))

    # Sort by modification time desc (newest first)
    draft_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return draft_files


def _display_draft_releases(draft_files: list[Path], title: str = "Draft Releases"):
    """
    Display a table of draft release files.

    Args:
        draft_files: List of Path objects for draft release files
        title: Title for the table
    """
    if not draft_files:
        console.print("[yellow]No draft releases found.[/yellow]")
        return

    table = Table(title=title)
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


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('version', required=False)
@click.option('--list', '-l', 'list_drafts', is_flag=True, help='List draft releases ready to be published')
@click.option('--notes-file', '-f', type=click.Path(), help='Path to release notes file (markdown, optional - will auto-find if not specified)')
@click.option('--release/--no-release', 'create_release', default=None, help='Create GitHub release (default: from config)')
@click.option('--pr/--no-pr', 'create_pr', default=None, help='Create PR with release notes (default: from config)')
@click.option('--draft/--no-draft', 'draft', default=None, help='Create as draft release (default: from config)')
@click.option('--prerelease', type=click.Choice(['auto', 'true', 'false'], case_sensitive=False), default=None,
              help='Mark as prerelease: auto (detect from version), true, or false (default: from config)')
@click.option('--dry-run', is_flag=True, help='Show what would be published without making changes')
@click.option('--debug', is_flag=True, help='Show detailed debug information')
@click.pass_context
def publish(ctx, version: Optional[str], list_drafts: bool, notes_file: Optional[str], create_release: Optional[bool],
           create_pr: Optional[bool], draft: Optional[bool], prerelease: Optional[str],
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
        draft_files = _find_draft_releases(config)
        _display_draft_releases(draft_files)
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

        # Handle tri-state prerelease: "auto", "true", "false"
        prerelease_value = prerelease if prerelease is not None else config.output.prerelease

        # Convert string values to appropriate types
        if isinstance(prerelease_value, str):
            if prerelease_value.lower() == "true":
                prerelease_flag = True
                prerelease_auto = False
            elif prerelease_value.lower() == "false":
                prerelease_flag = False
                prerelease_auto = False
            else:  # "auto"
                prerelease_flag = False  # Will be set based on version
                prerelease_auto = True
        else:
            # Boolean value from config
            prerelease_flag = prerelease_value
            prerelease_auto = False

        if debug:
            console.print("\n[bold cyan]Debug Mode: Configuration & Settings[/bold cyan]")
            console.print("[dim]" + "=" * 60 + "[/dim]")
            console.print(f"[dim]Repository:[/dim] {config.repository.code_repo}")
            console.print(f"[dim]Dry run:[/dim] {dry_run}")
            console.print(f"[dim]Operations that will be performed:[/dim]")
            console.print(f"[dim]  • Create GitHub release: {create_release} (CLI override: {create_release is not None})[/dim]")
            console.print(f"[dim]  • Create PR: {create_pr} (CLI override: {create_pr is not None})[/dim]")
            console.print(f"[dim]  • Draft release: {draft} (CLI override: {draft is not None})[/dim]")
            console.print(f"[dim]  • Prerelease setting: {prerelease_value} (CLI override: {prerelease is not None})[/dim]")
            console.print(f"[dim]  • Prerelease auto-detect: {prerelease_auto}[/dim]")
            console.print("[dim]" + "=" * 60 + "[/dim]\n")

        # Parse version
        target_version = SemanticVersion.parse(version)

        if debug:
            console.print("[bold cyan]Debug Mode: Version Information[/bold cyan]")
            console.print("[dim]" + "=" * 60 + "[/dim]")
            console.print(f"[dim]Version:[/dim] {target_version.to_string()}")
            console.print(f"[dim]  • Major: {target_version.major}[/dim]")
            console.print(f"[dim]  • Minor: {target_version.minor}[/dim]")
            console.print(f"[dim]  • Patch: {target_version.patch}[/dim]")
            console.print(f"[dim]  • Is final release: {target_version.is_final()}[/dim]")
            console.print(f"[dim]Git tag:[/dim] v{version}")
            console.print("[dim]" + "=" * 60 + "[/dim]\n")

        # Auto-detect prerelease if set to "auto" and version is not final
        if prerelease_auto and not target_version.is_final():
            prerelease_flag = True
            if debug:
                console.print(f"[blue]✓ Auto-detected as prerelease version (version is not final)[/blue]")
            elif not dry_run:
                console.print(f"[blue]Auto-detected as prerelease version[/blue]")

        if debug:
            console.print(f"[dim]Final prerelease flag:[/dim] {prerelease_flag}\n")

        # Read release notes
        notes_path = None
        release_notes = None

        if debug:
            console.print("[bold cyan]Debug Mode: Release Notes[/bold cyan]")
            console.print("[dim]" + "=" * 60 + "[/dim]")

        if notes_file:
            notes_path = Path(notes_file)
            if not notes_path.exists():
                console.print(f"[red]Error: Notes file not found: {notes_file}[/red]")
                sys.exit(1)
            release_notes = notes_path.read_text()
            if debug:
                console.print(f"[dim]Source:[/dim] Explicit file (--notes-file)")
                console.print(f"[dim]Path:[/dim] {notes_path}")
                console.print(f"[dim]Size:[/dim] {len(release_notes)} characters")
                console.print(f"[dim]File exists:[/dim] Yes")
            elif not dry_run:
                console.print(f"[blue]Loaded release notes from {notes_file}[/blue]")
        else:
            # Try to auto-find draft notes for this version
            if debug:
                console.print(f"[dim]Source:[/dim] Auto-finding (no --notes-file specified)")
                console.print(f"[dim]Search pattern:[/dim] {config.output.draft_output_path}")
                console.print(f"[dim]Searching for version:[/dim] {version}")

            matching_drafts = _find_draft_releases(config, version_filter=version)

            if debug:
                console.print(f"[dim]Matches found:[/dim] {len(matching_drafts)}")

            if len(matching_drafts) == 1:
                # Found exactly one match, use it
                notes_path = matching_drafts[0]
                release_notes = notes_path.read_text()
                if debug:
                    console.print(f"[dim]Path:[/dim] {notes_path}")
                    console.print(f"[dim]Size:[/dim] {len(release_notes)} characters")
                else:
                    console.print(f"[blue]Auto-found release notes from {notes_path}[/blue]")
            elif len(matching_drafts) == 0:
                # No draft found, error and list all available drafts
                console.print(f"[red]Error: No draft release notes found for version {version}[/red]")
                console.print("[yellow]Available draft releases:[/yellow]\n")
                all_drafts = _find_draft_releases(config)
                _display_draft_releases(all_drafts, title="Available Draft Releases")
                console.print(f"\n[yellow]Tip: Generate release notes first with:[/yellow]")
                console.print(f"[dim]  release-tool generate {version}[/dim]")
                sys.exit(1)
            else:
                # Multiple matches found, error and list them
                console.print(f"[red]Error: Multiple draft release notes found for version {version}[/red]")
                console.print("[yellow]Matching drafts:[/yellow]\n")
                _display_draft_releases(matching_drafts, title="Matching Draft Releases")
                console.print(f"\n[yellow]Please specify one with --notes-file[/yellow]")
                sys.exit(1)

        if debug:
            # Show preview of release notes
            if release_notes:
                preview_length = 300
                preview = release_notes[:preview_length]
                if len(release_notes) > preview_length:
                    preview += "\n[... truncated ...]"
                console.print(f"\n[dim]Preview:[/dim]")
                console.print(f"[dim]{preview}[/dim]")
            console.print("[dim]" + "=" * 60 + "[/dim]\n")

        # Initialize GitHub client (only if not dry-run)
        github_client = None if dry_run else GitHubClient(config)
        repo_name = config.repository.code_repo

        if debug:
            console.print("[bold cyan]Debug Mode: GitHub Operations[/bold cyan]")
            console.print("[dim]" + "=" * 60 + "[/dim]")
            console.print(f"[dim]Repository:[/dim] {repo_name}")
            console.print(f"[dim]Git tag:[/dim] v{version}")
            console.print(f"[dim]GitHub client initialized:[/dim] {not dry_run}")
            console.print("[dim]" + "=" * 60 + "[/dim]\n")

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
            if not notes_path:
                console.print("[yellow]Warning: No release notes available, skipping PR creation.[/yellow]")
                console.print("[dim]Tip: Generate release notes first or specify with --notes-file[/dim]")
            else:
                # Format PR templates
                version_parts = {
                    'version': version,
                    'major': str(target_version.major),
                    'minor': str(target_version.minor),
                    'patch': str(target_version.patch)
                }

                # Try to count changes from release notes for PR body template
                num_changes = 0
                num_categories = 0
                if release_notes:
                    # Simple heuristic: count markdown list items (lines starting with - or *)
                    lines = release_notes.split('\n')
                    num_changes = sum(1 for line in lines if line.strip().startswith(('- ', '* ')))
                    # Count category headers (lines starting with ###)
                    num_categories = sum(1 for line in lines if line.strip().startswith('###'))

                version_parts.update({
                    'num_changes': num_changes if num_changes > 0 else 'several',
                    'num_categories': num_categories if num_categories > 0 else 'multiple'
                })

                branch_name = config.output.pr_templates.branch_template.format(**version_parts)
                pr_title = config.output.pr_templates.title_template.format(**version_parts)

                # Use safe formatting for PR body in case template has other variables
                try:
                    pr_body = config.output.pr_templates.body_template.format(**version_parts)
                except KeyError as e:
                    # If template has variables we don't provide, use a simpler default
                    if debug:
                        console.print(f"[dim]Warning: PR body template has unsupported variable {e}, using simplified body[/dim]")
                    pr_body = f"Automated release notes for version {version}."

                if debug:
                    console.print("\n[bold cyan]Debug Mode: Pull Request Details[/bold cyan]")
                    console.print("[dim]" + "=" * 60 + "[/dim]")
                    console.print(f"[dim]Branch name:[/dim] {branch_name}")
                    console.print(f"[dim]PR title:[/dim] {pr_title}")
                    console.print(f"[dim]Target branch:[/dim] {config.output.pr_target_branch}")
                    console.print(f"[dim]Notes file:[/dim] {notes_path}")
                    console.print(f"\n[dim]PR body:[/dim]")
                    console.print(f"[dim]{pr_body}[/dim]")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                if dry_run:
                    console.print(f"[yellow]Would create pull request:[/yellow]")
                    console.print(f"[yellow]  Branch: {branch_name}[/yellow]")
                    console.print(f"[yellow]  Title: {pr_title}[/yellow]")
                    console.print(f"[yellow]  Target: {config.output.pr_target_branch}[/yellow]")
                    console.print(f"[yellow]  Notes file: {notes_path}[/yellow]")
                    console.print(f"\n[yellow]PR body:[/yellow]")
                    console.print(f"[dim]{pr_body}[/dim]\n")
                else:
                    console.print(f"[blue]Creating PR with release notes...[/blue]")
                    github_client.create_pr_for_release_notes(
                        repo_name,
                        pr_title,
                        str(notes_path),
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
                console.print("\n[bold cyan]Debug Mode: Docusaurus Documentation[/bold cyan]")
                console.print("[dim]" + "=" * 60 + "[/dim]")
                console.print(f"[dim]Configured path template:[/dim] {config.output.doc_output_path}")
                console.print(f"[dim]Resolved path:[/dim] {doc_path}")
                console.print(f"[dim]File exists:[/dim] {doc_file.exists()}")

            if doc_file.exists():
                # Read doc file content for preview in debug mode
                doc_content = None
                if debug:
                    try:
                        doc_content = doc_file.read_text()
                        console.print(f"[dim]File size:[/dim] {len(doc_content)} characters ({doc_file.stat().st_size} bytes)")
                    except Exception as e:
                        console.print(f"[dim]Error reading file:[/dim] {e}")

                # Show preview in debug mode
                if debug and doc_content:
                    preview_length = 400
                    preview = doc_content[:preview_length]
                    if len(doc_content) > preview_length:
                        preview += "\n[... truncated ...]"
                    console.print(f"\n[dim]Content preview:[/dim]")
                    console.print(f"[dim]{preview}[/dim]")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                if dry_run:
                    console.print(f"[yellow]Docusaurus file: {doc_path}[/yellow]")
                    console.print(f"[yellow]  Status: File exists ({doc_file.stat().st_size} bytes)[/yellow]")
                    console.print(f"[yellow]  Note: You may want to commit this file to your repository[/yellow]")
                    console.print(f"[dim]  Example: git add {doc_path} && git commit -m \"Add release notes for {version}\"[/dim]")
                elif not debug:
                    console.print(f"[blue]Docusaurus file found at {doc_file}[/blue]")
                    console.print(f"[dim]Note: You may want to commit this file to your repository.[/dim]")
                    console.print(f"[dim]Example: git add {doc_path} && git commit -m \"Add release notes for {version}\"[/dim]")
            else:
                if debug:
                    console.print(f"[dim]Status:[/dim] File not found")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")
                elif dry_run:
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
