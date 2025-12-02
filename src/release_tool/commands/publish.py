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
from ..models import SemanticVersion, Release
from ..template_utils import render_template, validate_template_vars, get_template_variables, TemplateError
from ..git_ops import GitOperations, determine_release_branch_strategy

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
    db: Database,
    template_context: dict,
    version: str,
    override: bool = False,
    dry_run: bool = False,
    debug: bool = False
) -> Optional[dict]:
    """
    Create or update a GitHub issue for tracking the release.

    Args:
        config: Configuration object
        github_client: GitHub client instance
        db: Database instance for checking/saving associations
        template_context: Template context for rendering ticket templates
        version: Release version
        override: If True, reuse existing ticket if found
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
    repo_full_name = config.repository.code_repo

    # Prepare labels
    final_labels = config.output.ticket_templates.labels.copy()
    # Note: Issue type is handled separately via GraphQL, not as a label

    # Prepare milestone
    milestone_obj = None
    milestone_name = None
    
    if config.output.ticket_templates.milestone:
        try:
            milestone_name = render_template(
                config.output.ticket_templates.milestone,
                template_context
            )
            if not dry_run:
                milestone_obj = github_client.get_milestone_by_title(issues_repo, milestone_name)
        except TemplateError as e:
            console.print(f"[red]Error rendering milestone template: {e}[/red]")

    # Check for existing ticket association if override is enabled
    existing_association = db.get_ticket_association(repo_full_name, version) if not dry_run else None
    result = None

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

    if existing_association and override:
        # Reuse existing ticket
        if debug or not dry_run:
            console.print(f"[blue]Reusing existing ticket #{existing_association['ticket_number']} (--force)[/blue]")
            console.print(f"[dim]  URL: {existing_association['ticket_url']}[/dim]")

        if not dry_run:
            github_client.update_issue(
                repo_full_name=issues_repo,
                issue_number=existing_association['ticket_number'],
                title=title,
                body=body,
                labels=final_labels,
                milestone=milestone_obj
            )
            
            # Update issue type if specified
            if config.output.ticket_templates.type:
                github_client.set_issue_type(
                    repo_full_name=issues_repo,
                    issue_number=existing_association['ticket_number'],
                    type_name=config.output.ticket_templates.type
                )

            console.print(f"[green]Updated ticket #{existing_association['ticket_number']} details (title, body, labels, milestone, type)[/green]")

        result = {
            'number': str(existing_association['ticket_number']),
            'url': existing_association['ticket_url']
        }
    elif existing_association and not override:
        console.print(f"[yellow]Warning: Ticket already exists for {version} (#{existing_association['ticket_number']})[/yellow]")
        console.print(f"[yellow]Use --force \\[draft|release] to reuse the existing ticket[/yellow]")
        console.print(f"[dim]  URL: {existing_association['ticket_url']}[/dim]")
        return None
    else:
        # Create new ticket
        if dry_run or debug:
            console.print("\n[cyan]Release Tracking Ticket:[/cyan]")
            console.print(f"  Repository: {issues_repo}")
            console.print(f"  Title: {title}")
            console.print(f"  Labels: {', '.join(final_labels)}")
            if config.output.ticket_templates.type:
                console.print(f"  Issue Type: {config.output.ticket_templates.type}")
            if milestone_name:
                console.print(f"  Milestone: {milestone_name}")

            # Show assignee if configured
            assignee = config.output.ticket_templates.assignee
            if not assignee and not dry_run:
                # Get current user if not dry-run
                assignee = github_client.get_authenticated_user() if github_client else "current user"
            console.print(f"  Assignee: {assignee or 'current user'}")

            # Show project assignment if configured
            if config.output.ticket_templates.project_id:
                console.print(f"  Project ID: {config.output.ticket_templates.project_id}")
                if config.output.ticket_templates.project_status:
                    console.print(f"  Project Status: {config.output.ticket_templates.project_status}")
                if config.output.ticket_templates.project_fields:
                    console.print(f"  Project Fields: {config.output.ticket_templates.project_fields}")

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
            labels=final_labels,
            milestone=milestone_obj,
            issue_type=config.output.ticket_templates.type
        )

        if result:
            # Save association to database
            db.save_ticket_association(
                repo_full_name=repo_full_name,
                version=version,
                ticket_number=int(result['number']),
                ticket_url=result['url']
            )

            if debug:
                console.print(f"[dim]Saved ticket association to database[/dim]")

    if not result:
        return None

    # Assign issue to user (for both new and updated tickets)
    if not dry_run:
        assignee = config.output.ticket_templates.assignee
        if not assignee:
            assignee = github_client.get_authenticated_user()

        if assignee:
            github_client.assign_issue(
                repo_full_name=issues_repo,
                issue_number=int(result['number']),
                assignee=assignee
            )

        # Add to project if configured (for both new and updated tickets)
        if config.output.ticket_templates.project_id:
            # Resolve project ID (number) to node ID
            org_name = issues_repo.split('/')[0]
            try:
                project_number = int(config.output.ticket_templates.project_id)
                project_node_id = github_client.get_project_node_id(org_name, project_number)
                
                if project_node_id:
                    github_client.assign_issue_to_project(
                        issue_url=result['url'],
                        project_id=project_node_id,
                        status=config.output.ticket_templates.project_status,
                        custom_fields=config.output.ticket_templates.project_fields,
                        debug=debug
                    )
            except ValueError:
                console.print(f"[yellow]Warning: Invalid project ID '{config.output.ticket_templates.project_id}'. Expected a number.[/yellow]")

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
@click.option('--delete', '-d', 'delete_drafts', is_flag=True, help='Delete draft releases for the specified version')
@click.option('--notes-file', '-f', type=click.Path(), help='Path to release notes file (markdown, optional - will auto-find if not specified)')
@click.option('--release/--no-release', 'create_release', default=None, help='Create GitHub release (default: from config)')
@click.option('--pr/--no-pr', 'create_pr', default=None, help='Create PR with release notes (default: from config)')
@click.option('--release-mode', type=click.Choice(['draft', 'published'], case_sensitive=False), default=None, help='Release mode (default: from config)')
@click.option('--prerelease', type=click.Choice(['auto', 'true', 'false'], case_sensitive=False), default=None,
              help='Mark as prerelease: auto (detect from version), true, or false (default: from config)')
@click.option('--force', type=click.Choice(['none', 'draft', 'published'], case_sensitive=False), default='none', help='Force overwrite existing release (default: none)')
@click.option('--dry-run', is_flag=True, help='Show what would be published without making changes')
@click.option('--debug', is_flag=True, help='Show detailed debug information')
@click.pass_context
def publish(ctx, version: Optional[str], list_drafts: bool, delete_drafts: bool, notes_file: Optional[str], create_release: Optional[bool],
           create_pr: Optional[bool], release_mode: Optional[str], prerelease: Optional[str], force: str,
           dry_run: bool, debug: bool):
    """
    Publish a release to GitHub.

    Creates a GitHub release and/or pull request with release notes.
    Release notes can be read from a file or will be loaded from the database.

    Flags default to config values but can be overridden via CLI.

    Examples:

      release-tool publish 9.1.0 -f docs/releases/9.1.0.md

      release-tool publish 9.1.0-rc.0 --release-mode draft

      release-tool publish 9.1.0 --pr --no-release

      release-tool publish 9.1.0 -f notes.md --dry-run

      release-tool publish 9.1.0 -f notes.md --debug
    """
    config: Config = ctx.obj['config']

    if list_drafts:
        draft_files = _find_draft_releases(config)
        _display_draft_releases(draft_files)

        # Show tip with an example version if drafts exist
        if draft_files:
            # Extract version from the first (newest) draft
            first_file = draft_files[0]
            filename = first_file.stem
            version_str = filename
            if filename.endswith("-doc"):
                version_str = filename[:-4]
            elif filename.endswith("-release"):
                version_str = filename[:-8]

            console.print(f"\n[yellow]Tip: Publish a release with:[/yellow]")
            console.print(f"[dim]  release-tool publish {version_str}[/dim]")

        return

    # Handle --delete flag
    if delete_drafts:
        if not version:
            console.print("[red]Error: VERSION required when using --delete[/red]")
            console.print("\nUsage: release-tool publish --delete VERSION")
            sys.exit(1)

        # Find drafts for this version
        matching_drafts = _find_draft_releases(config, version_filter=version)

        if not matching_drafts:
            console.print(f"[yellow]No draft releases found for version {version}[/yellow]")
            console.print("\n[dim]Available drafts:[/dim]")
            all_drafts = _find_draft_releases(config)
            _display_draft_releases(all_drafts, title="Available Draft Releases")
            return

        # Display what will be deleted
        console.print(f"\n[yellow]Found {len(matching_drafts)} draft file(s) for version {version}:[/yellow]")
        for draft_path in matching_drafts:
            console.print(f"  - {draft_path}")

        # Confirm deletion (skip confirmation if non-interactive or dry-run)
        if not dry_run:
            response = input(f"\nDelete {len(matching_drafts)} file(s)? [y/N]: ").strip().lower()
            if response not in ['y', 'yes']:
                console.print("[yellow]Deletion cancelled.[/yellow]")
                return

        # Delete the files
        deleted_count = 0
        for draft_path in matching_drafts:
            if dry_run:
                console.print(f"[yellow]Would delete: {draft_path}[/yellow]")
            else:
                try:
                    draft_path.unlink()
                    console.print(f"[green]✓ Deleted: {draft_path}[/green]")
                    deleted_count += 1
                except Exception as e:
                    console.print(f"[red]Error deleting {draft_path}: {e}[/red]")

        if not dry_run:
            console.print(f"\n[green]✓ Deleted {deleted_count} of {len(matching_drafts)} draft file(s)[/green]")

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
        
        # Resolve release mode
        # If force is set to a mode, it overrides release_mode
        if force != 'none':
            mode = force
        else:
            mode = release_mode if release_mode is not None else config.output.release_mode
            
        is_draft = (mode == 'draft')

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
            console.print(f"[dim]  • Release mode: {mode} (CLI override: {release_mode is not None or force != 'none'})[/dim]")
            console.print(f"[dim]  • Force: {force}[/dim]")
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
                
                # Show tip with an available version if any exist
                if all_drafts:
                    # Extract version from the first (newest) draft
                    first_file = all_drafts[0]
                    filename = first_file.stem
                    example_version = filename
                    if filename.endswith("-doc"):
                        example_version = filename[:-4]
                    elif filename.endswith("-release"):
                        example_version = filename[:-8]
                    
                    console.print(f"\n[yellow]Tip: Use an existing draft or generate new notes:[/yellow]")
                    console.print(f"[dim]  release-tool publish {example_version}[/dim]")
                    console.print(f"[dim]  release-tool generate {version}[/dim]")
                else:
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

        # Initialize GitHub client and database
        github_client = None if dry_run else GitHubClient(config)
        repo_name = config.repository.code_repo

        # Calculate issue_repo_name
        issues_repo = _get_issues_repo(config)
        issue_repo_name = issues_repo.split('/')[-1] if '/' in issues_repo else issues_repo

        # Initialize GitOperations and determine target_branch
        git_ops = GitOperations('.')
        available_versions = git_ops.get_version_tags()
        
        target_branch, _, _ = determine_release_branch_strategy(
            version=target_version,
            git_ops=git_ops,
            available_versions=available_versions,
            branch_template=config.branch_policy.release_branch_template,
            default_branch=config.repository.default_branch,
            branch_from_previous=config.branch_policy.branch_from_previous_release
        )

        # Initialize database connection
        db = Database(config.database.path)
        db.connect()

        # Check for existing release
        repo = db.get_repository(repo_name)
        if repo:
            existing_release = db.get_release(repo.id, version)
            if existing_release:
                if force == 'none':
                    console.print(f"[red]Error: Release {version} already exists.[/red]")
                    console.print(f"[yellow]Use --force \\[draft|published] to overwrite.[/yellow]")
                    sys.exit(1)
                elif not dry_run:
                    console.print(f"[yellow]Warning: Overwriting existing release {version} (--force {force})[/yellow]")

        if debug:
            console.print("[bold cyan]Debug Mode: GitHub Operations[/bold cyan]")
            console.print("[dim]" + "=" * 60 + "[/dim]")
            console.print(f"[dim]Repository:[/dim] {repo_name}")
            console.print(f"[dim]Git tag:[/dim] v{version}")
            console.print(f"[dim]GitHub client initialized:[/dim] {not dry_run}")
            console.print(f"[dim]Database path:[/dim] {config.database.path}")
            console.print(f"[dim]Force mode:[/dim] {force}")
            console.print("[dim]" + "=" * 60 + "[/dim]\n")

        # Dry-run banner
        if dry_run:
            console.print(f"\n[yellow]{'='*80}[/yellow]")
            console.print(f"[yellow]DRY RUN - Publish release {version}[/yellow]")
            console.print(f"[yellow]{'='*80}[/yellow]\n")

        # Create GitHub release
        if create_release:
            status = "draft " if is_draft else ("prerelease " if prerelease_flag else "")
            release_type = "draft" if is_draft else ("prerelease" if prerelease_flag else "final release")

            if dry_run:
                console.print(f"[yellow]Would create {status}GitHub release:[/yellow]")
                console.print(f"[yellow]  Repository: {repo_name}[/yellow]")
                console.print(f"[yellow]  Version: {version}[/yellow]")
                console.print(f"[yellow]  Tag: v{version}[/yellow]")
                console.print(f"[yellow]  Type: {release_type.capitalize()}[/yellow]")
                console.print(f"[yellow]  Status: {'Draft' if is_draft else 'Published'}[/yellow]")
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
                    draft=is_draft,
                    target_commitish=target_branch
                )
                console.print(f"[green]✓ GitHub release created successfully[/green]")
                console.print(f"[blue]→ https://github.com/{repo_name}/releases/tag/v{version}[/blue]")
        elif dry_run:
            console.print(f"[yellow]Would NOT create GitHub release (--no-release or config setting)[/yellow]\n")

        # Save release to database
        if not dry_run and repo:
            release = Release(
                repo_id=repo.id,
                version=version,
                tag_name=f"v{version}",
                name=f"Release {version}",
                body=release_notes,
                created_at=datetime.now(),
                published_at=datetime.now() if not is_draft else None,
                is_draft=is_draft,
                is_prerelease=prerelease_flag,
                url=f"https://github.com/{repo_name}/releases/tag/v{version}",
                target_commitish=target_branch
            )
            db.upsert_release(release)
            if debug:
                console.print(f"[dim]Saved release to database (is_draft={is_draft})[/dim]")

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
                
                # Calculate date-based variables
                now = datetime.now()
                quarter = (now.month - 1) // 3 + 1
                quarter_uppercase = f"Q{quarter}"

                template_context = {
                    'code_repo': config.repository.code_repo.replace('/', '-'),
                    'issue_repo': issues_repo,
                    'issue_repo_name': issue_repo_name,
                    'pr_link': 'PR_LINK_PLACEHOLDER',
                    'version': version,
                    'major': str(target_version.major),
                    'minor': str(target_version.minor),
                    'patch': str(target_version.patch),
                    'year': str(now.year),
                    'quarter_uppercase': quarter_uppercase,
                    'num_changes': num_changes if num_changes > 0 else 'several',
                    'num_categories': num_categories if num_categories > 0 else 'multiple',
                    'target_branch': target_branch
                }

                # Create release tracking ticket if enabled
                ticket_result = None
                
                # If force=draft, try to find existing ticket interactively first if not in DB
                if config.output.create_ticket and force == 'draft' and not dry_run:
                     existing_association = db.get_ticket_association(repo_name, version)
                     if not existing_association:
                         ticket_result = _find_existing_ticket_interactive(config, github_client, version)
                         if ticket_result:
                             console.print(f"[blue]Reusing existing ticket #{ticket_result['number']}[/blue]")
                             # Save association
                             db.save_ticket_association(
                                repo_full_name=repo_name,
                                version=version,
                                ticket_number=int(ticket_result['number']),
                                ticket_url=ticket_result['url']
                            )

                if not ticket_result:
                    ticket_result = _create_release_ticket(
                        config=config,
                        github_client=github_client,
                        db=db,
                        template_context=template_context,
                        version=version,
                        override=(force != 'none'),
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
                    
                    # Determine which file(s) to include in the PR
                    # If Docusaurus output is enabled, we prioritize it and suppress the default release output
                    # to avoid double commits and unwanted files.
                    additional_files = {}
                    
                    if doc_output_enabled and doc_notes_content:
                         # Use Docusaurus file as the primary file
                         pr_file_path = render_template(config.output.doc_output_path, template_context)
                         pr_content = doc_notes_content
                         if debug:
                             console.print(f"[dim]Using Docusaurus output as primary PR file: {pr_file_path}[/dim]")
                    else:
                         # Use default release output
                         pr_file_path = render_template(config.output.release_output_path, template_context)
                         pr_content = release_notes
                         if debug:
                             console.print(f"[dim]Using standard release output as primary PR file: {pr_file_path}[/dim]")
                    
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
                    console.print(f"[dim]Target branch:[/dim] {target_branch}")
                    console.print(f"[dim]Primary file path:[/dim] {pr_file_path}")
                    if additional_files:
                        for path in additional_files:
                            console.print(f"[dim]Additional file:[/dim] {path}")
                    console.print(f"\n[dim]PR body:[/dim]")
                    console.print(f"[dim]{pr_body}[/dim]")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                if dry_run:
                    console.print(f"[yellow]Would create pull request:[/yellow]")
                    console.print(f"[yellow]  Branch: {branch_name}[/yellow]")
                    console.print(f"[yellow]  Title: {pr_title}[/yellow]")
                    console.print(f"[yellow]  Target: {target_branch}[/yellow]")
                    console.print(f"[yellow]  Primary file:[/yellow] {pr_file_path}")
                    if additional_files:
                        for path in additional_files:
                            console.print(f"[yellow]  Additional file:[/yellow] {path}")
                    console.print(f"\n[yellow]PR body:[/yellow]")
                    console.print(f"[dim]{pr_body}[/dim]\n")
                else:
                    console.print(f"[blue]Creating PR with release notes...[/blue]")
                    pr_url = github_client.create_pr_for_release_notes(
                        repo_name,
                        pr_title,
                        pr_file_path,
                        pr_content,
                        branch_name,
                        target_branch,
                        pr_body,
                        additional_files=additional_files
                    )
                    
                    if pr_url:
                        console.print(f"[green]✓ Pull request processed successfully[/green]")

                        # Update ticket body with real PR link
                        if ticket_result and not dry_run:
                            try:
                                repo = github_client.gh.get_repo(issues_repo)
                                issue = repo.get_issue(int(ticket_result['number']))
                                
                                # Check if we need to update the link
                                if issue.body and 'PR_LINK_PLACEHOLDER' in issue.body:
                                    new_body = issue.body.replace('PR_LINK_PLACEHOLDER', pr_url)
                                    github_client.update_issue_body(issues_repo, int(ticket_result['number']), new_body)
                                    console.print(f"[green]Updated ticket #{ticket_result['number']} with PR link[/green]")
                            except Exception as e:
                                console.print(f"[yellow]Warning: Could not update ticket body with PR link: {e}[/yellow]")
                    else:
                        console.print(f"[red]Failed to create or find PR[/red]")
        elif dry_run:
            console.print(f"[yellow]Would NOT create pull request (--no-pr or config setting)[/yellow]\n")

        # Handle Docusaurus file if configured (only if PR creation didn't handle it)
        if doc_output_enabled and not create_pr:
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
    finally:
        # Close database connection if it was opened
        if 'db' in locals() and db:
            db.close()


def _find_existing_ticket_interactive(config: Config, github_client: GitHubClient, version: str) -> Optional[dict]:
    """Find existing ticket interactively."""
    issues_repo = _get_issues_repo(config)
    query = f"repo:{issues_repo} is:issue {version} in:title"
    console.print(f"[cyan]Searching for existing tickets in {issues_repo}...[/cyan]")
    
    # We need to use the underlying github client to search
    # This is a bit of a hack, but we don't have a search method in GitHubClient
    # Assuming github_client.gh is available
    issues = list(github_client.gh.search_issues(query)[:5])
    
    if not issues:
        console.print("[yellow]No matching tickets found.[/yellow]")
        return None
        
    table = Table(title="Found Tickets")
    table.add_column("#", style="cyan")
    table.add_column("Number", style="green")
    table.add_column("Title", style="white")
    table.add_column("State", style="yellow")
    
    for i, issue in enumerate(issues):
        table.add_row(str(i+1), str(issue.number), issue.title, issue.state)
        
    console.print(table)
    
    response = input("\nSelect ticket to reuse (1-5) or 'n' to create new: ").strip().lower()
    if response.isdigit() and 1 <= int(response) <= len(issues):
        selected = issues[int(response)-1]
        return {'number': str(selected.number), 'url': selected.html_url}
        
    return None
