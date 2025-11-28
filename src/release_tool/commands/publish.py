import sys
from pathlib import Path
from typing import Optional
from collections import defaultdict
from datetime import datetime
import click
from rich.console import Console
from rich.table import Table

from ..config import Config
from ..db import Database
from ..github_utils import GitHubClient
from ..models import SemanticVersion
from ..template_utils import render_template, validate_template_vars, get_template_variables, TemplateError

console = Console()


def _get_issues_repo(config: Config) -> str:
    """
    Get the issues repository from config.

    Returns the first ticket_repos entry if available, otherwise falls back to code_repo.
    """
    if config.repository.ticket_repos and len(config.repository.ticket_repos) > 0:
        return config.repository.ticket_repos[0]
    return config.repository.code_repo


def _create_release_ticket(
    config: Config,
    github_client: GitHubClient,
    template_context: dict,
    dry_run: bool = False,
    debug: bool = False
) -> Optional[dict]:
    """
    Create a GitHub issue for tracking the release.

    Args:
        config: Configuration object
        github_client: GitHub client instance
        template_context: Template context for rendering ticket templates
        dry_run: If True, only show what would be created
        debug: If True, show verbose output

    Returns:
        Dictionary with 'number' and 'url' keys if created, None otherwise
    """
    if not config.output.create_ticket:
        if debug:
            console.print("[dim]Ticket creation disabled (create_ticket=false)[/dim]")
        return None

    issues_repo = _get_issues_repo(config)

    # Render ticket templates
    try:
        title = render_template(
            config.output.ticket_templates.title_template,
            template_context
        )
        body = render_template(
            config.output.ticket_templates.body_template,
            template_context
        )
    except TemplateError as e:
        console.print(f"[red]Error rendering ticket template: {e}[/red]")
        return None

    if dry_run or debug:
        console.print("\n[cyan]Release Tracking Ticket:[/cyan]")
        console.print(f"  Repository: {issues_repo}")
        console.print(f"  Title: {title}")
        console.print(f"  Labels: {', '.join(config.output.ticket_templates.labels)}")

    if debug:
        console.print(f"\n[dim]Body:[/dim]")
        console.print(f"[dim]{'─' * 60}[/dim]")
        console.print(f"[dim]{body}[/dim]")
        console.print(f"[dim]{'─' * 60}[/dim]\n")

    if dry_run:
        return {'number': 'XXXX', 'url': f'https://github.com/{issues_repo}/issues/XXXX'}

    # Create the issue
    if debug:
        console.print(f"[cyan]Creating ticket in {issues_repo}...[/cyan]")

    result = github_client.create_issue(
        repo_full_name=issues_repo,
        title=title,
        body=body,
        labels=config.output.ticket_templates.labels
    )

    return result


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
    # We replace Jinja2 placeholders {{variable}} with * to match any value
    if version_filter:
        # If filtering by version, keep the version in the pattern
        glob_pattern = template.replace("{{code_repo}}", "*")\
                               .replace("{{issue_repo}}", "*")\
                               .replace("{{version}}", version_filter)\
                               .replace("{{major}}", "*")\
                               .replace("{{minor}}", "*")\
                               .replace("{{minor}}", "*")\
                               .replace("{{patch}}", "*")\
                               .replace("{{output_file_type}}", "*")
    else:
        # Match all versions
        glob_pattern = template.replace("{{code_repo}}", "*")\
                               .replace("{{issue_repo}}", "*")\
                               .replace("{{version}}", "*")\
                               .replace("{{major}}", "*")\
                               .replace("{{minor}}", "*")\
                               .replace("{{patch}}", "*")\
                               .replace("{{output_file_type}}", "*")

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
    table.add_column("Release Type", style="yellow")  # RC or Final
    table.add_column("Content Type", style="magenta") # Doc, Release
    table.add_column("Created", style="blue")
    table.add_column("Path(s)", style="dim")

    # Group by (repo_name, version_str)
    grouped_drafts = defaultdict(list)
    
    for file_path in draft_files:
        # Extract repo name
        repo_name = file_path.parent.name
        
        # Extract version from filename
        # Filename format: version-type.md or version.md
        filename = file_path.stem
        
        # Simple heuristic to strip suffix if present
        version_str = filename
        content_type = "Release"
        
        if filename.endswith("-doc"):
            version_str = filename[:-4]
            content_type = "Doc"
        elif filename.endswith("-release"):
            version_str = filename[:-8]
            content_type = "Release"
            
        grouped_drafts[(repo_name, version_str)].append({
            'path': file_path,
            'content_type': content_type,
            'mtime': file_path.stat().st_mtime
        })

    # Sort groups by mtime of newest file in group
    sorted_groups = sorted(
        grouped_drafts.items(),
        key=lambda item: max(f['mtime'] for f in item[1]),
        reverse=True
    )

    for (repo_name, version_str), files in sorted_groups:
        try:
            version_obj = SemanticVersion.parse(version_str)
            rel_type = "RC" if not version_obj.is_final() else "Final"
        except ValueError:
            rel_type = "Unknown"

        # Collect content types and paths
        content_types = sorted(list(set(f['content_type'] for f in files)))
        content_type_str = ", ".join(content_types)
        
        # Get newest creation time
        newest_mtime = max(f['mtime'] for f in files)
        created_str = datetime.fromtimestamp(newest_mtime).strftime("%Y-%m-%d %H:%M")
        
        # Format paths (newline separated)
        paths_str = "\n".join(str(f['path']) for f in files)

        table.add_row(
            repo_name,
            version_str,
            rel_type,
            content_type_str,
            created_str,
            paths_str
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
        doc_output_enabled = config.output.doc_output_path is not None

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
            console.print(f"[dim]  • Documentation output enabled: {doc_output_enabled}[/dim]")
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
        doc_notes_path = None
        doc_notes_content = None

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
                # Multiple matches found. Separate release and doc drafts
                release_candidates = [d for d in matching_drafts if "doc" not in d.name.lower()]
                doc_candidates = [d for d in matching_drafts if "doc" in d.name.lower()]
                
                # Handle release notes
                if len(release_candidates) == 1:
                     notes_path = release_candidates[0]
                     release_notes = notes_path.read_text()
                     if debug:
                        console.print(f"[dim]Multiple drafts found, selected release candidate:[/dim] {notes_path}")
                     else:
                        console.print(f"[blue]Auto-found release notes from {notes_path}[/blue]")
                elif len(release_candidates) == 0:
                    # If we have doc drafts but no release drafts, that might be an issue if we expected release notes
                    # But maybe the user only wants to publish docs? 
                    # For now, let's assume we need release notes.
                    console.print(f"[red]Error: No release notes draft found for version {version}[/red]")
                    if doc_candidates:
                        console.print(f"[dim](Found {len(doc_candidates)} doc drafts, but need release notes)[/dim]")
                    sys.exit(1)
                else:
                    # Ambiguous release notes
                    console.print(f"[red]Error: Multiple release note drafts found for version {version}[/red]")
                    _display_draft_releases(release_candidates, title="Ambiguous Release Drafts")
                    sys.exit(1)

                # Handle doc notes
                if len(doc_candidates) == 1:
                    doc_notes_path = doc_candidates[0]
                    doc_notes_content = doc_notes_path.read_text()
                    if debug:
                        console.print(f"[dim]Selected doc candidate:[/dim] {doc_notes_path}")
                elif len(doc_candidates) > 1:
                    if debug:
                        console.print(f"[yellow]Warning: Multiple doc drafts found, ignoring:[/yellow]")
                        for d in doc_candidates:
                            console.print(f"  - {d}")

        if debug:
            # Show full release notes in debug mode
            if release_notes:
                console.print(f"\n[bold]Full Release Notes Content:[/bold]")
                console.print(f"[dim]{'─' * 60}[/dim]")
                console.print(release_notes)
                console.print(f"[dim]{'─' * 60}[/dim]")
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

                # Show release notes preview (only if not in debug mode to avoid duplication)
                if not debug:
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
                # Build template context with all available variables
                # Try to count changes from release notes for PR body template
                num_changes = 0
                num_categories = 0
                if release_notes:
                    # Simple heuristic: count markdown list items (lines starting with - or *)
                    lines = release_notes.split('\n')
                    num_changes = sum(1 for line in lines if line.strip().startswith(('- ', '* ')))
                    # Count category headers (lines starting with ###)
                    num_categories = sum(1 for line in lines if line.strip().startswith('###'))

                # Build initial template context
                issues_repo = _get_issues_repo(config)

                template_context = {
                    'code_repo': config.repository.code_repo.replace('/', '-'),
                    'issue_repo': issues_repo,
                    'version': version,
                    'major': str(target_version.major),
                    'minor': str(target_version.minor),
                    'patch': str(target_version.patch),
                    'num_changes': num_changes if num_changes > 0 else 'several',
                    'num_categories': num_categories if num_categories > 0 else 'multiple',
                    'target_branch': config.output.pr_target_branch
                }

                # Create release tracking ticket if enabled
                ticket_result = _create_release_ticket(
                    config=config,
                    github_client=github_client if not dry_run else None,
                    template_context=template_context,
                    dry_run=dry_run,
                    debug=debug
                )

                # Add ticket variables to context if ticket was created
                if ticket_result:
                    template_context.update({
                        'issue_number': ticket_result['number'],
                        'issue_link': ticket_result['url']
                    })

                    if debug:
                        console.print("\n[bold cyan]Debug Mode: Ticket Information[/bold cyan]")
                        console.print("[dim]" + "=" * 60 + "[/dim]")
                        console.print(f"[dim]Ticket created:[/dim] Yes")
                        console.print(f"[dim]Issue number:[/dim] {ticket_result['number']}")
                        console.print(f"[dim]Issue URL:[/dim] {ticket_result['url']}")
                        console.print(f"[dim]Repository:[/dim] {_get_issues_repo(config)}")
                        console.print(f"\n[dim]Template variables now available:[/dim]")
                        for var in sorted(template_context.keys()):
                            console.print(f"[dim]  • {{{{{var}}}}}: {template_context[var]}[/dim]")
                        console.print("[dim]" + "=" * 60 + "[/dim]\n")
                elif debug:
                    console.print("\n[bold cyan]Debug Mode: Ticket Information[/bold cyan]")
                    console.print("[dim]" + "=" * 60 + "[/dim]")
                    console.print(f"[dim]Ticket creation:[/dim] {'Disabled (create_ticket=false)' if not config.output.create_ticket else 'Failed or dry-run'}")
                    console.print(f"\n[dim]Template variables available (without ticket):[/dim]")
                    for var in sorted(template_context.keys()):
                        console.print(f"[dim]  • {{{{{{var}}}}}}: {template_context[var]}[/dim]")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                # Define which variables are available
                available_vars = set(template_context.keys())
                ticket_vars = {'issue_number', 'issue_link'}

                # Validate templates don't use ticket variables when they're not available
                # (either because create_ticket=false or ticket creation failed)
                if not ticket_result:
                    # Check each template for ticket variables
                    for template_name, template_str in [
                        ('branch_template', config.output.pr_templates.branch_template),
                        ('title_template', config.output.pr_templates.title_template),
                        ('body_template', config.output.pr_templates.body_template)
                    ]:
                        try:
                            used_vars = get_template_variables(template_str)
                            invalid_vars = used_vars & ticket_vars
                            if invalid_vars:
                                console.print(
                                    f"[red]Error: PR {template_name} uses ticket variables "
                                    f"({', '.join(sorted(invalid_vars))}) but create_ticket is disabled[/red]"
                                )
                                console.print("[yellow]Either enable create_ticket in config or update the template.[/yellow]")
                                sys.exit(1)
                        except TemplateError as e:
                            console.print(f"[red]Error in PR {template_name}: {e}[/red]")
                            sys.exit(1)

                # Render templates using Jinja2
                try:
                    branch_name = render_template(config.output.pr_templates.branch_template, template_context)
                    pr_title = render_template(config.output.pr_templates.title_template, template_context)
                    pr_body = render_template(config.output.pr_templates.body_template, template_context)
                except TemplateError as e:
                    console.print(f"[red]Error rendering PR template: {e}[/red]")
                    if debug:
                        raise
                    sys.exit(1)

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
        if doc_output_enabled:
            template_context = {
                'version': version,
                'major': str(target_version.major),
                'minor': str(target_version.minor),
                'patch': str(target_version.patch)
            }
            try:
                doc_path = render_template(config.output.doc_output_path, template_context)
            except TemplateError as e:
                console.print(f"[red]Error rendering doc_output_path template: {e}[/red]")
                if debug:
                    raise
                sys.exit(1)
            doc_file = Path(doc_path)

            if debug:
                console.print("\n[bold cyan]Debug Mode: Documentation Release Notes[/bold cyan]")
                console.print("[dim]" + "=" * 60 + "[/dim]")
                console.print(f"[dim]Doc template configured:[/dim] {config.release_notes.doc_output_template is not None}")
                console.print(f"[dim]Doc path template:[/dim] {config.output.doc_output_path}")
                console.print(f"[dim]Resolved final path:[/dim] {doc_path}")
                console.print(f"[dim]Draft source path:[/dim] {doc_notes_path if doc_notes_path else 'None'}")
                console.print(f"[dim]Draft content found:[/dim] {doc_notes_content is not None}")

            if doc_notes_content:
                # We have draft content to write
                console.print(f"\n[bold]Full Doc Notes Content:[/bold]")
                console.print(f"[dim]{'─' * 60}[/dim]")
                console.print(doc_notes_content)
                console.print(f"[dim]{'─' * 60}[/dim]")
                console.print("[dim]" + "=" * 60 + "[/dim]\n")

                if dry_run:
                    console.print(f"[yellow]Would write documentation to: {doc_path}[/yellow]")
                    console.print(f"[yellow]  Source: {doc_notes_path}[/yellow]")
                    console.print(f"[yellow]  Size: {len(doc_notes_content)} characters[/yellow]")
                else:
                    doc_file.parent.mkdir(parents=True, exist_ok=True)
                    doc_file.write_text(doc_notes_content)
                    console.print(f"[green]✓ Documentation written to:[/green]")
                    console.print(f"[green]  {doc_file}[/green]")
                    
            elif doc_file.exists():
                # Fallback: File exists but we didn't find a draft. 
                # This might happen if we didn't run generate or if we're just re-publishing.
                # Just report it.
                if debug:
                    try:
                        existing_content = doc_file.read_text()
                        console.print(f"[dim]Existing file size:[/dim] {len(existing_content)} characters")
                    except Exception as e:
                        console.print(f"[dim]Error reading file:[/dim] {e}")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                if dry_run:
                    console.print(f"[yellow]Existing Docusaurus file found: {doc_path}[/yellow]")
                    console.print(f"[dim]No new draft content found to update it.[/dim]")
                elif not debug:
                    console.print(f"[blue]Existing Docusaurus file found at {doc_file}[/blue]")
            else:
                if debug:
                    console.print(f"[dim]Status:[/dim] No draft found and no existing file")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")
                elif dry_run:
                    console.print(f"[dim]No documentation draft found and no existing file at {doc_path}[/dim]")

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
