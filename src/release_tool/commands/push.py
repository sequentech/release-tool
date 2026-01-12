# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

import sys
import time
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
from ..template_utils import render_template, validate_template_vars, get_template_variables, TemplateError, build_repo_context
from ..git_ops import GitOperations, determine_release_branch_strategy

console = Console()


def _get_issues_repo(config: Config) -> str:
    """
    Get the issues repository from config.

    Returns the first issue_repos entry if available, otherwise falls back to code_repo.
    """
    if config.repository.issue_repos and len(config.repository.issue_repos) > 0:
        return config.repository.issue_repos[0]
    return config.repository.code_repo


def _create_release_issue(
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
        template_context: Template context for rendering issue templates
        version: Release version
        override: If True, reuse existing issue if found
        dry_run: If True, only show what would be created
        debug: If True, show verbose output

    Returns:
        Dictionary with 'number' and 'url' keys if created, None otherwise
    """
    if not config.output.create_issue:
        if debug:
            console.print("[dim]Issue creation disabled (create_issue=false)[/dim]")
        return None

    issues_repo = _get_issues_repo(config)
    repo_full_name = config.repository.code_repo

    # Prepare labels
    final_labels = config.output.issue_templates.labels.copy()
    # Note: Issue type is handled separately via GraphQL, not as a label

    # Prepare milestone
    milestone_obj = None
    milestone_name = None
    
    if config.output.issue_templates.milestone:
        try:
            milestone_name = render_template(
                config.output.issue_templates.milestone,
                template_context
            )
            if not dry_run:
                milestone_obj = github_client.get_milestone_by_title(issues_repo, milestone_name)
        except TemplateError as e:
            console.print(f"[red]Error rendering milestone template: {e}[/red]")

    # Check for existing issue association if override is enabled
    existing_association = db.get_issue_association(repo_full_name, version) if not dry_run else None
    result = None

    # Render issue templates
    try:
        title = render_template(
            config.output.issue_templates.title_template,
            template_context
        )
        body = render_template(
            config.output.issue_templates.body_template,
            template_context
        )
    except TemplateError as e:
        console.print(f"[red]Error rendering issue template: {e}[/red]")
        return None

    if existing_association and override:
        # Reuse existing issue
        if debug or not dry_run:
            console.print(f"[blue]Reusing existing issue #{existing_association['issue_number']} (--force)[/blue]")
            console.print(f"[dim]  URL: {existing_association['issue_url']}[/dim]")

        if not dry_run:
            github_client.update_issue(
                repo_full_name=issues_repo,
                issue_number=existing_association['issue_number'],
                title=title,
                body=body,
                labels=final_labels,
                milestone=milestone_obj
            )
            
            # Update issue type if specified
            if config.output.issue_templates.type:
                github_client.set_issue_type(
                    repo_full_name=issues_repo,
                    issue_number=existing_association['issue_number'],
                    type_name=config.output.issue_templates.type
                )

            console.print(f"[green]Updated issue #{existing_association['issue_number']} details (title, body, labels, milestone, type)[/green]")

        result = {
            'number': str(existing_association['issue_number']),
            'url': existing_association['issue_url']
        }
    elif existing_association and not override:
        console.print(f"[yellow]Warning: Issue already exists for {version} (#{existing_association['issue_number']})[/yellow]")
        console.print(f"[yellow]Use --force \\[draft|release] to reuse the existing issue[/yellow]")
        console.print(f"[dim]  URL: {existing_association['issue_url']}[/dim]")
        return None
    else:
        # Create new issue
        if dry_run or debug:
            console.print("\n[cyan]Release Tracking Issue:[/cyan]")
            console.print(f"  Repository: {issues_repo}")
            console.print(f"  Title: {title}")
            console.print(f"  Labels: {', '.join(final_labels)}")
            if config.output.issue_templates.type:
                console.print(f"  Issue Type: {config.output.issue_templates.type}")
            if milestone_name:
                console.print(f"  Milestone: {milestone_name}")

            # Show assignee if configured
            assignee = config.output.issue_templates.assignee
            if not assignee and not dry_run:
                # Get current user if not dry-run
                assignee = github_client.get_authenticated_user() if github_client else "current user"
            console.print(f"  Assignee: {assignee or 'current user'}")

            # Show project assignment if configured
            if config.output.issue_templates.project_id:
                console.print(f"  Project ID: {config.output.issue_templates.project_id}")
                if config.output.issue_templates.project_status:
                    console.print(f"  Project Status: {config.output.issue_templates.project_status}")
                if config.output.issue_templates.project_fields:
                    console.print(f"  Project Fields: {config.output.issue_templates.project_fields}")

        if debug:
            console.print(f"\n[dim]Body:[/dim]")
            console.print(f"[dim]{'─' * 60}[/dim]")
            console.print(f"[dim]{body}[/dim]")
            console.print(f"[dim]{'─' * 60}[/dim]\n")

        if dry_run:
            return {'number': 'XXXX', 'url': f'https://github.com/{issues_repo}/issues/XXXX'}

        # Create the issue
        if debug:
            console.print(f"[cyan]Creating issue in {issues_repo}...[/cyan]")

        result = github_client.create_issue(
            repo_full_name=issues_repo,
            title=title,
            body=body,
            labels=final_labels,
            milestone=milestone_obj,
            issue_type=config.output.issue_templates.type
        )

        if result:
            # Save association to database
            db.save_issue_association(
                repo_full_name=repo_full_name,
                version=version,
                issue_number=int(result['number']),
                issue_url=result['url']
            )

            if debug:
                console.print(f"[dim]Saved issue association to database[/dim]")

    if not result:
        return None

    # Assign issue to user (for both new and updated issues)
    if not dry_run:
        assignee = config.output.issue_templates.assignee
        if not assignee:
            assignee = github_client.get_authenticated_user()

        if assignee:
            github_client.assign_issue(
                repo_full_name=issues_repo,
                issue_number=int(result['number']),
                assignee=assignee
            )

        # Add to project if configured (for both new and updated issues)
        if config.output.issue_templates.project_id:
            # Resolve project ID (number) to node ID
            org_name = issues_repo.split('/')[0]
            try:
                project_number = int(config.output.issue_templates.project_id)
                project_node_id = github_client.get_project_node_id(org_name, project_number)
                
                if project_node_id:
                    github_client.assign_issue_to_project(
                        issue_url=result['url'],
                        project_id=project_node_id,
                        status=config.output.issue_templates.project_status,
                        custom_fields=config.output.issue_templates.project_fields,
                        debug=debug
                    )
            except ValueError:
                console.print(f"[yellow]Warning: Invalid project ID '{config.output.issue_templates.project_id}'. Expected a number.[/yellow]")

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

    # Use glob from the appropriate base path
    # If pattern is absolute, use its parent directory; otherwise use current directory
    glob_path = Path(glob_pattern)
    if glob_path.is_absolute():
        # Find the first wildcard position to determine the base path
        parts = glob_path.parts
        base_parts = []
        pattern_parts = []
        found_wildcard = False

        for part in parts:
            if '*' in part or found_wildcard:
                found_wildcard = True
                pattern_parts.append(part)
            else:
                base_parts.append(part)

        if base_parts:
            base_path = Path(*base_parts)
            relative_pattern = str(Path(*pattern_parts)) if pattern_parts else "*"
        else:
            # Pattern starts with wildcard, use root
            base_path = Path('/')
            relative_pattern = str(Path(*parts[1:]))

        draft_files = list(base_path.glob(relative_pattern))
    else:
        # Relative path, use current directory
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
        elif "-code-" in filename:
            # Handle code-N format (e.g., "1.0.0-code-0" -> version="1.0.0", type="Code 0")
            parts = filename.rsplit("-code-", 1)
            if len(parts) == 2:
                version_str = parts[0]
                code_num = parts[1]
                content_type = f"Code {code_num}"

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
@click.option('--list', '-l', 'list_drafts', is_flag=True, help='List draft releases ready to be pushed')
@click.option('--delete', '-d', 'delete_drafts', is_flag=True, help='Delete draft releases for the specified version')
@click.option('--notes-file', '-f', type=click.Path(), help='Path to release notes file (markdown, optional - will auto-find if not specified)')
@click.option('--release/--no-release', 'create_release', default=None, help='Create GitHub release (default: from config)')
@click.option('--pr/--no-pr', 'create_pr', default=None, help='Create PR with release notes (default: from config)')
@click.option('--release-mode', type=click.Choice(['draft', 'published', 'mark-published'], case_sensitive=False), default=None, help='Release mode: draft, published, or mark-published (mark existing draft release as published without recreating)')
@click.option('--prerelease', type=click.Choice(['auto', 'true', 'false'], case_sensitive=False), default=None,
              help='Mark as prerelease: auto (detect from version), true, or false (default: from config)')
@click.option('--force', type=click.Choice(['none', 'draft', 'published'], case_sensitive=False), default='none', help='Force overwrite existing release (default: none)')
@click.option('--issue', type=int, default=None, help='Issue/issue number to associate with this release')
@click.option('--dry-run', is_flag=True, help='Show what would be pushed without making changes')
@click.pass_context
def push(ctx, version: Optional[str], list_drafts: bool, delete_drafts: bool, notes_file: Optional[str], create_release: Optional[bool],
           create_pr: Optional[bool], release_mode: Optional[str], prerelease: Optional[str], force: str, issue: Optional[int],
           dry_run: bool):
    """
    Push a release to GitHub.

    Creates a GitHub release and/or pull request with release notes.
    Release notes can be read from a file or will be loaded from the database.

    Flags default to config values but can be overridden via CLI.

    Examples:

      release-tool push 9.1.0 -f docs/releases/9.1.0.md

      release-tool push 9.1.0-rc.0 --release-mode draft

      release-tool push 9.1.0 --pr --no-release

      release-tool push 9.1.0 -f notes.md --dry-run

      release-tool push 9.1.0 -f notes.md --debug
    """
    # Get debug flag from global context
    debug = ctx.obj.get('debug', False)

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
            elif "-code-" in filename:
                # Handle code-N format (e.g., "1.0.0-code-0")
                parts = filename.rsplit("-code-", 1)
                if len(parts) == 2:
                    version_str = parts[0]

            console.print(f"\n[yellow]Tip: Push a release with:[/yellow]")
            console.print(f"[dim]  release-tool push {version_str}[/dim]")

        return

    # Handle --delete flag
    if delete_drafts:
        if not version:
            console.print("[red]Error: VERSION required when using --delete[/red]")
            console.print("\nUsage: release-tool push --delete VERSION")
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
        console.print("\nUsage: release-tool push [OPTIONS] VERSION")
        console.print("Try 'release-tool push --help' for help.")
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
        
        # Handle mark-published mode: only mark existing draft release as published
        is_mark_published = (mode == 'mark-published')
        is_draft = (mode == 'draft')

        # Handle tri-state prerelease: "auto", "true", "false"
        prerelease_value = prerelease if prerelease is not None else config.output.prerelease
        # Check if pr_code templates are configured (replaces doc_output_path check)
        doc_output_enabled = bool(config.output.pr_code.templates)

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
            console.print(f"[dim]Repository:[/dim] {config.get_primary_code_repo().link}")
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
                    elif "-code-" in filename:
                        # Handle code-N format (e.g., "1.0.0-code-0")
                        parts = filename.rsplit("-code-", 1)
                        if len(parts) == 2:
                            example_version = parts[0]

                    console.print(f"\n[yellow]Tip: Use an existing draft or generate new notes:[/yellow]")
                    console.print(f"[dim]  release-tool push {example_version}[/dim]")
                    console.print(f"[dim]  release-tool generate {version}[/dim]")
                else:
                    console.print(f"\n[yellow]Tip: Generate release notes first with:[/yellow]")
                    console.print(f"[dim]  release-tool generate {version}[/dim]")
                sys.exit(1)
            else:
                # Multiple matches found. Separate into release, doc, and code drafts
                release_candidates = [d for d in matching_drafts if "-release" in d.stem]
                doc_candidates = [d for d in matching_drafts if "-doc" in d.stem]
                code_candidates = [d for d in matching_drafts if "-code-" in d.stem]

                # Handle release notes (for GitHub release)
                if len(release_candidates) == 1:
                     notes_path = release_candidates[0]
                     release_notes = notes_path.read_text()
                     if debug:
                        console.print(f"[dim]Multiple drafts found, selected release candidate:[/dim] {notes_path}")
                     else:
                        console.print(f"[blue]Auto-found release notes from {notes_path}[/blue]")
                elif len(release_candidates) == 0:
                    # No explicit release file - this is expected if only code templates are configured
                    # For backward compatibility, also check if there are any non-code, non-doc files
                    other_candidates = [d for d in matching_drafts if d not in doc_candidates and d not in code_candidates]
                    if len(other_candidates) == 1:
                        notes_path = other_candidates[0]
                        release_notes = notes_path.read_text()
                        if debug:
                            console.print(f"[dim]Selected non-code/doc candidate as release notes:[/dim] {notes_path}")
                    elif create_release:
                        # User wants to create GitHub release but no release file found
                        console.print(f"[red]Error: No GitHub release draft found for version {version}[/red]")
                        if code_candidates or doc_candidates:
                            console.print(f"[dim](Found {len(code_candidates)} code and {len(doc_candidates)} doc drafts)[/dim]")
                            console.print(f"[yellow]Tip: Code/doc drafts found but no GitHub release draft (-release)[/yellow]")
                        sys.exit(1)
                else:
                    # Ambiguous release notes
                    console.print(f"[red]Error: Multiple release note drafts found for version {version}[/red]")
                    _display_draft_releases(release_candidates, title="Ambiguous Release Drafts")
                    sys.exit(1)

                # Handle doc notes (deprecated - will be replaced by code-N files)
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

                # Handle code notes (for PR creation) - use code-0 if available
                if len(code_candidates) >= 1:
                    # Sort to get code-0 first
                    code_candidates_sorted = sorted(code_candidates, key=lambda p: p.stem)
                    doc_notes_path = code_candidates_sorted[0]  # Use code-0 for PR
                    doc_notes_content = doc_notes_path.read_text()
                    if debug:
                        console.print(f"[dim]Selected code candidate for PR:[/dim] {doc_notes_path}")

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
        # Fetch remote refs first to ensure accurate branch detection
        git_ops.fetch_remote_refs()
        available_versions = git_ops.get_version_tags()

        target_branch, source_branch, should_create_branch = determine_release_branch_strategy(
            version=target_version,
            git_ops=git_ops,
            available_versions=available_versions,
            branch_template=config.branch_policy.release_branch_template,
            default_branch=config.branch_policy.default_branch,
            branch_from_previous=config.branch_policy.branch_from_previous_release
        )

        # Handle release branch creation/fetching (before creating GitHub release)
        if should_create_branch and config.branch_policy.create_branches:
            if debug:
                console.print(f"[dim]Release branch {target_branch} doesn't exist locally. Creating from {source_branch}...[/dim]")

            if not dry_run:
                try:
                    # Check if branch exists remotely first
                    if git_ops.branch_exists(target_branch, remote=True):
                        # Branch exists remotely, fetch it instead of creating
                        if debug:
                            console.print(f"[dim]Branch exists remotely, fetching {target_branch}...[/dim]")
                        try:
                            git_ops.repo.git.fetch('origin', f"{target_branch}:{target_branch}")
                            if debug:
                                console.print(f"[dim]✓ Fetched {target_branch} from remote[/dim]")
                        except Exception as fetch_error:
                            console.print(f"[yellow]Warning: Could not fetch {target_branch}: {fetch_error}[/yellow]")
                    else:
                        # Branch doesn't exist remotely, create and push
                        git_ops.create_branch(target_branch, source_branch)
                        git_ops.push_branch(target_branch)
                        if debug:
                            console.print(f"[dim]✓ Created and pushed {target_branch} to remote[/dim]")
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not create/push release branch: {e}[/yellow]")
                    console.print(f"[yellow]Continuing with release creation...[/yellow]")
            elif debug:
                console.print(f"[yellow]Would create and push branch {target_branch} from {source_branch}[/yellow]")
        else:
            if debug:
                console.print(f"[dim]Using existing release branch {target_branch}[/dim]")
                
            # Even if not creating, ensure we have the branch locally if it exists remotely
            if not dry_run and not git_ops.branch_exists(target_branch) and git_ops.branch_exists(target_branch, remote=True):
                try:
                    git_ops.repo.git.fetch('origin', f"{target_branch}:{target_branch}")
                    if debug:
                        console.print(f"[dim]✓ Fetched {target_branch} from remote[/dim]")
                except Exception as e:
                    if debug:
                        console.print(f"[dim]Could not fetch {target_branch}: {e}[/dim]")

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
            console.print(f"[yellow]DRY RUN - Push release {version}[/yellow]")
            console.print(f"[yellow]{'='*80}[/yellow]\n")

        # Create GitHub release
        if create_release:
            tag_name = f"v{version}"
            release_url = None  # Will be set by create/update operations

            # Handle mark-published mode: only update existing draft release to published
            if is_mark_published:
                if dry_run:
                    console.print(f"[yellow]Would mark existing GitHub release as published:[/yellow]")
                    console.print(f"[yellow]  Repository: {repo_name}[/yellow]")
                    console.print(f"[yellow]  Version: {version}[/yellow]")
                    console.print(f"[yellow]  Tag: {tag_name}[/yellow]")
                else:
                    # Check if release exists
                    existing_gh_release = github_client.get_release_by_tag(repo_name, tag_name)
                    
                    if not existing_gh_release:
                        console.print(f"[red]Error: No existing GitHub release found for {tag_name}[/red]")
                        console.print(f"[yellow]Use --release-mode published or draft to create a new release[/yellow]")
                        sys.exit(1)
                    
                    # Update existing release to published (draft=False)
                    console.print(f"[blue]Marking existing GitHub release as published for {version}...[/blue]")
                    if debug:
                        console.print(f"[dim]Existing release URL: {existing_gh_release.html_url}[/dim]")
                        console.print(f"[dim]Current draft status: {existing_gh_release.draft}[/dim]")
                    
                    release_url = github_client.update_release(
                        repo_name,
                        tag_name,
                        name=existing_gh_release.title or f"Release {version}",
                        body=existing_gh_release.body or "",
                        prerelease=existing_gh_release.prerelease,
                        draft=False,  # Mark as published
                        target_commitish=existing_gh_release.target_commitish
                    )
                    
                    if release_url:
                        console.print(f"[green]✓ GitHub release marked as published successfully[/green]")
                        console.print(f"[blue]→ {release_url}[/blue]")
                    else:
                        console.print(f"[red]✗ Failed to update GitHub release[/red]")
                        sys.exit(1)
            else:
                # Normal mode: create or update release with full tag/notes handling
                status = "draft " if is_draft else ("prerelease " if prerelease_flag else "")
                release_type = "draft" if is_draft else ("prerelease" if prerelease_flag else "final release")

                if dry_run:
                    console.print(f"[yellow]Would create git tag and {status}GitHub release:[/yellow]")
                    console.print(f"[yellow]  Repository: {repo_name}[/yellow]")
                    console.print(f"[yellow]  Version: {version}[/yellow]")
                    console.print(f"[yellow]  Tag: {tag_name}[/yellow]")
                    console.print(f"[yellow]  Target: {target_branch}[/yellow]")
                    console.print(f"[yellow]  Type: {release_type.capitalize()}[/yellow]")
                    console.print(f"[yellow]  Status: {'Draft' if is_draft else 'Published'}[/yellow]")
                    console.print(f"[yellow]  URL: https://github.com/{repo_name}/releases/tag/{tag_name}[/yellow]")

                    # Show release notes preview (only if not in debug mode to avoid duplication)
                    if not debug:
                        preview_length = 500
                        preview = release_notes[:preview_length]
                        if len(release_notes) > preview_length:
                            preview += "\n[... truncated ...]"
                        console.print(f"\n[yellow]Release notes preview ({len(release_notes)} characters):[/yellow]")
                        console.print(f"[dim]{preview}[/dim]\n")
                else:
                    # Create and push git tag before creating GitHub release
                    tag_exists_locally = git_ops.tag_exists(tag_name, remote=False)
                    tag_exists_remotely = git_ops.tag_exists(tag_name, remote=True)
                    should_force_tag = force != 'none'
                    
                    # Handle local tag
                    if not tag_exists_locally:
                        if debug:
                            console.print(f"[dim]Creating git tag {tag_name} at {target_branch}...[/dim]")
                        try:
                            git_ops.create_tag(tag_name, ref=target_branch, message=f"Release {version}")
                            if debug:
                                console.print(f"[dim]✓ Created local tag {tag_name}[/dim]")
                            else:
                                console.print(f"[blue]✓ Created local tag {tag_name}[/blue]")
                        except Exception as e:
                            console.print(f"[red]Error creating git tag: {e}[/red]")
                            sys.exit(1)
                    elif should_force_tag:
                        # Delete and recreate local tag when forcing
                        if debug:
                            console.print(f"[dim]Force: Deleting and recreating local tag {tag_name} at {target_branch}...[/dim]")
                        try:
                            git_ops.repo.delete_tag(tag_name)
                            git_ops.create_tag(tag_name, ref=target_branch, message=f"Release {version}")
                            if debug:
                                console.print(f"[dim]✓ Force-created local tag {tag_name}[/dim]")
                            else:
                                console.print(f"[blue]✓ Force-created local tag {tag_name}[/blue]")
                        except Exception as e:
                            console.print(f"[red]Error force-creating git tag: {e}[/red]")
                            sys.exit(1)
                    elif debug:
                        console.print(f"[dim]Tag {tag_name} already exists locally[/dim]")

                    # Push tag to remote
                    if not tag_exists_remotely:
                        if debug:
                            console.print(f"[dim]Pushing tag {tag_name} to remote...[/dim]")
                        try:
                            git_ops.push_tag(tag_name)
                            if debug:
                                console.print(f"[dim]✓ Pushed tag {tag_name} to remote[/dim]")
                            else:
                                console.print(f"[blue]✓ Pushed tag {tag_name} to remote[/blue]")
                        except Exception as e:
                            console.print(f"[red]Error pushing git tag: {e}[/red]")
                            sys.exit(1)
                    elif should_force_tag:
                        # Force push tag when forcing
                        if debug:
                            console.print(f"[dim]Force-pushing tag {tag_name} to remote...[/dim]")
                        try:
                            git_ops.push_tag(tag_name, force=True)
                            if debug:
                                console.print(f"[dim]✓ Force-pushed tag {tag_name} to remote[/dim]")
                            else:
                                console.print(f"[blue]✓ Force-pushed tag {tag_name} to remote[/blue]")
                        except Exception as e:
                            console.print(f"[red]Error force-pushing git tag: {e}[/red]")
                            sys.exit(1)
                    else:
                        if debug:
                            console.print(f"[dim]Tag {tag_name} already exists on remote[/dim]")
                        # Even if tag exists, still try to push in case local is ahead
                        # This handles the case where the tag might exist but not be on the correct commit
                        try:
                            git_ops.push_tag(tag_name)
                            if debug:
                                console.print(f"[dim]✓ Pushed tag {tag_name} to remote (update)[/dim]")
                        except Exception as e:
                            # Non-fatal - tag might already be at correct commit
                            if debug:
                                console.print(f"[dim]Tag push skipped (already up to date or would fail): {e}[/dim]")

                    # Wait for GitHub to index the tag (prevent "untagged" releases)
                    if debug:
                        console.print(f"[dim]Waiting for GitHub to index tag {tag_name}...[/dim]")
                    time.sleep(2)  # 2 second delay to allow GitHub to process the tag
                    
                    # Check if release already exists on GitHub
                    existing_gh_release = github_client.get_release_by_tag(repo_name, tag_name)
                    
                    if existing_gh_release:
                        if force == 'none':
                            console.print(f"[red]Error: GitHub release {tag_name} already exists.[/red]")
                            console.print(f"[yellow]Use --force [draft|published] to update the existing release.[/yellow]")
                            console.print(f"[dim]  URL: {existing_gh_release.html_url}[/dim]")
                            sys.exit(1)
                        else:
                            # Update existing release
                            console.print(f"[blue]Updating existing {status}GitHub release for {version}...[/blue]")
                            if debug:
                                console.print(f"[dim]Existing release URL: {existing_gh_release.html_url}[/dim]")
                            
                            release_name = f"Release {version}"
                            release_url = github_client.update_release(
                                repo_name,
                                tag_name,
                                name=release_name,
                                body=release_notes,
                                prerelease=prerelease_flag,
                                draft=is_draft,
                                target_commitish=target_branch
                            )
                            
                            if release_url:
                                console.print(f"[green]✓ GitHub release updated successfully[/green]")
                                console.print(f"[blue]→ {release_url}[/blue]")
                            else:
                                console.print(f"[red]✗ Failed to update GitHub release[/red]")
                                sys.exit(1)
                    else:
                        # Create new release
                        console.print(f"[blue]Creating {status}GitHub release for {version}...[/blue]")

                        release_name = f"Release {version}"
                        release_url = github_client.create_release(
                            repo_name,
                            version,
                            release_name,
                            release_notes,
                            prerelease=prerelease_flag,
                            draft=is_draft,
                            target_commitish=target_branch
                        )

                        if release_url:
                            console.print(f"[green]✓ GitHub release created successfully[/green]")
                            console.print(f"[blue]→ {release_url}[/blue]")
                            
                            # Verify the release URL doesn't contain "untagged"
                            if "untagged" in release_url:
                                console.print(f"[yellow]⚠ Warning: Release created but appears to be untagged. This may indicate the git tag was not properly created.[/yellow]")
                                console.print(f"[yellow]  Expected tag: {tag_name}[/yellow]")
                                console.print(f"[yellow]  Please verify the tag exists: git tag -l {tag_name}[/yellow]")
                        else:
                            console.print(f"[red]✗ Failed to create GitHub release[/red]")
                            console.print(f"[red]Error: Release creation failed. See error message above for details.[/red]")
                            sys.exit(1)

            # Save release to database
            if not dry_run and repo:
                # Use the actual release URL from GitHub if available, otherwise construct it
                actual_url = release_url if release_url else f"https://github.com/{repo_name}/releases/tag/v{version}"

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
                    url=actual_url,
                    target_commitish=target_branch
                )
                db.upsert_release(release)
            if debug:
                console.print(f"[dim]Saved release to database (is_draft={is_draft})[/dim]")
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
                
                # Calculate date-based variables
                now = datetime.now()
                quarter = (now.month - 1) // 3 + 1
                quarter_uppercase = f"Q{quarter}"

                # Build template context with repo namespaces
                template_context = build_repo_context(config)
                template_context.update({
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
                })

                # Create release tracking issue if enabled
                issue_result = None
                
                # If issue number provided explicitly, use it directly
                if config.output.create_issue and issue and not dry_run:
                    try:
                        issue_obj = github_client.gh.get_repo(issues_repo).get_issue(issue)
                        issue_result = {'number': str(issue_obj.number), 'url': issue_obj.html_url}
                        console.print(f"[blue]Using provided issue #{issue}[/blue]")
                        # Save association to database
                        db.save_issue_association(
                            repo_full_name=repo_name,
                            version=version,
                            issue_number=issue_obj.number,
                            issue_url=issue_obj.html_url
                        )
                        if debug:
                            console.print(f"[dim]Saved issue association to database[/dim]")
                    except Exception as e:
                        console.print(f"[yellow]Warning: Could not use issue #{issue}: {e}[/yellow]")
                        issue_result = None
                
                # If force=draft, try to find existing issue automatically (non-interactive)
                if config.output.create_issue and force == 'draft' and not dry_run and not issue_result:
                     existing_association = db.get_issue_association(repo_name, version)
                     if not existing_association:
                         issue_result = _find_existing_issue_auto(config, github_client, version, debug)
                         if issue_result:
                             console.print(f"[blue]Auto-selected open issue #{issue_result['number']}[/blue]")
                             # Save association
                             db.save_issue_association(
                                repo_full_name=repo_name,
                                version=version,
                                issue_number=int(issue_result['number']),
                                issue_url=issue_result['url']
                            )

                if not issue_result:
                    issue_result = _create_release_issue(
                        config=config,
                        github_client=github_client,
                        db=db,
                        template_context=template_context,
                        version=version,
                        override=(force != 'none'),
                        dry_run=dry_run,
                        debug=debug
                    )

                # Add issue variables to context if issue was created
                if issue_result:
                    template_context.update({
                        'issue_number': issue_result['number'],
                        'issue_link': issue_result['url']
                    })

                    if debug:
                        console.print("\n[bold cyan]Debug Mode: Issue Information[/bold cyan]")
                        console.print("[dim]" + "=" * 60 + "[/dim]")
                        console.print(f"[dim]Issue created:[/dim] Yes")
                        console.print(f"[dim]Issue number:[/dim] {issue_result['number']}")
                        console.print(f"[dim]Issue URL:[/dim] {issue_result['url']}")
                        console.print(f"[dim]Repository:[/dim] {_get_issues_repo(config)}")
                        console.print(f"\n[dim]Template variables now available:[/dim]")
                        for var in sorted(template_context.keys()):
                            console.print(f"[dim]  • {{{{{var}}}}}: {template_context[var]}[/dim]")
                        console.print("[dim]" + "=" * 60 + "[/dim]\n")
                elif debug:
                    console.print("\n[bold cyan]Debug Mode: Issue Information[/bold cyan]")
                    console.print("[dim]" + "=" * 60 + "[/dim]")
                    console.print(f"[dim]Issue creation:[/dim] {'Disabled (create_issue=false)' if not config.output.create_issue else 'Failed or dry-run'}")
                    console.print(f"\n[dim]Template variables available (without issue):[/dim]")
                    for var in sorted(template_context.keys()):
                        console.print(f"[dim]  • {{{{{{var}}}}}}: {template_context[var]}[/dim]")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                # Define which variables are available
                available_vars = set(template_context.keys())
                issue_vars = {'issue_number', 'issue_link'}

                # Validate templates don't use issue variables when they're not available
                # (either because create_issue=false or issue creation failed)
                if not issue_result:
                    # Check each template for issue variables
                    for template_name, template_str in [
                        ('branch_template', config.output.pr_templates.branch_template),
                        ('title_template', config.output.pr_templates.title_template),
                        ('body_template', config.output.pr_templates.body_template)
                    ]:
                        try:
                            used_vars = get_template_variables(template_str)
                            invalid_vars = used_vars & issue_vars
                            if invalid_vars:
                                console.print(
                                    f"[red]Error: PR {template_name} uses issue variables "
                                    f"({', '.join(sorted(invalid_vars))}) but create_issue is disabled[/red]"
                                )
                                console.print("[yellow]Either enable create_issue in config or update the template.[/yellow]")
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
                    # If pr_code templates are configured, commit ALL code-N files to their output_path
                    additional_files = {}
                    pr_file_path = None
                    pr_content = None

                    if doc_output_enabled and config.output.pr_code.templates:
                        # For each pr_code template, find its draft file and map it to its output_path
                        for idx, pr_code_template in enumerate(config.output.pr_code.templates):
                            # Build context for rendering paths
                            path_template_context = build_repo_context(config)
                            path_template_context.update({
                                'version': version,
                                'major': str(target_version.major),
                                'minor': str(target_version.minor),
                                'patch': str(target_version.patch),
                                'output_file_type': f'code-{idx}'
                            })

                            # Determine the draft file path (where we READ from)
                            draft_file_path = render_template(config.output.draft_output_path, path_template_context)

                            # Determine the output path (where we COMMIT to)
                            commit_file_path = render_template(pr_code_template.output_path, path_template_context)

                            # Try to read content from draft file or from matching_drafts
                            content = None

                            # Check if we already have this content from auto-detection
                            if matching_drafts:
                                code_candidates = [d for d in matching_drafts if f"-code-{idx}" in d.stem]
                                if code_candidates:
                                    content = code_candidates[0].read_text()
                                    if debug:
                                        console.print(f"[dim]Auto-detected code-{idx} draft: {code_candidates[0]}[/dim]")

                            # If not found in auto-detection, try reading from rendered draft path
                            if not content:
                                draft_path_obj = Path(draft_file_path)
                                if draft_path_obj.exists():
                                    content = draft_path_obj.read_text()
                                    if debug:
                                        console.print(f"[dim]Found code-{idx} draft at: {draft_file_path}[/dim]")

                            # If we have content, add to PR
                            if content:
                                if idx == 0:
                                    # First template becomes the primary PR file
                                    pr_file_path = commit_file_path
                                    pr_content = content
                                    if debug:
                                        console.print(f"[dim]Primary PR file (code-0):[/dim]")
                                        console.print(f"[dim]  Draft source: {draft_file_path}[/dim]")
                                        console.print(f"[dim]  Commit destination: {commit_file_path}[/dim]")
                                else:
                                    # Additional templates go into additional_files
                                    additional_files[commit_file_path] = content
                                    if debug:
                                        console.print(f"[dim]Additional PR file (code-{idx}):[/dim]")
                                        console.print(f"[dim]  Draft source: {draft_file_path}[/dim]")
                                        console.print(f"[dim]  Commit destination: {commit_file_path}[/dim]")
                            elif debug:
                                console.print(f"[dim]No draft found for code-{idx} at {draft_file_path}[/dim]")

                        # Fallback if no pr_code files found
                        if not pr_file_path:
                            pr_file_path = None
                            pr_content = release_notes
                            if debug:
                                console.print(f"[dim]No pr_code draft files found, PR will have no file attachments[/dim]")
                    else:
                         # No templates configured - skip PR file
                         pr_file_path = None
                         pr_content = release_notes
                         if debug:
                             console.print(f"[dim]No pr_code templates configured, skipping PR file[/dim]")

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
                    if pr_file_path:
                        console.print(f"[dim]Primary file (will be committed to):[/dim] {pr_file_path}")
                    if additional_files:
                        console.print(f"[dim]Additional files (will be committed to):[/dim]")
                        for path in additional_files:
                            console.print(f"[dim]  - {path}[/dim]")
                    console.print(f"\n[dim]PR body:[/dim]")
                    console.print(f"[dim]{pr_body}[/dim]")
                    console.print("[dim]" + "=" * 60 + "[/dim]\n")

                if dry_run:
                    console.print(f"[yellow]Would create pull request:[/yellow]")
                    console.print(f"[yellow]  Branch: {branch_name}[/yellow]")
                    console.print(f"[yellow]  Title: {pr_title}[/yellow]")
                    console.print(f"[yellow]  Target: {target_branch}[/yellow]")
                    if pr_file_path:
                        console.print(f"[yellow]  Primary file (will be committed to): {pr_file_path}[/yellow]")
                    if additional_files:
                        console.print(f"[yellow]  Additional files (will be committed to):[/yellow]")
                        for path in additional_files:
                            console.print(f"[yellow]    - {path}[/yellow]")
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

                        # Update issue body with real PR link
                        if issue_result and not dry_run:
                            try:
                                repo = github_client.gh.get_repo(issues_repo)
                                issue = repo.get_issue(int(issue_result['number']))
                                
                                # Check if we need to update the link
                                if issue.body and 'PR_LINK_PLACEHOLDER' in issue.body:
                                    new_body = issue.body.replace('PR_LINK_PLACEHOLDER', pr_url)
                                    github_client.update_issue_body(issues_repo, int(issue_result['number']), new_body)
                                    console.print(f"[green]Updated issue #{issue_result['number']} with PR link[/green]")
                            except Exception as e:
                                console.print(f"[yellow]Warning: Could not update issue body with PR link: {e}[/yellow]")
                    else:
                        console.print(f"[red]✗ Failed to create or find PR[/red]")
                        console.print(f"[red]Error: PR creation failed. See error message above for details.[/red]")
                        sys.exit(1)
        elif dry_run:
            console.print(f"[yellow]Would NOT create pull request (--no-pr or config setting)[/yellow]\n")

        # Handle Docusaurus file if configured (only if PR creation didn't handle it)
        if doc_output_enabled and not create_pr:
            template_context_doc = build_repo_context(config)
            template_context_doc.update({
                'version': version,
                'major': str(target_version.major),
                'minor': str(target_version.minor),
                'patch': str(target_version.patch),
                'output_file_type': 'code-0'  # First pr_code template
            })
            try:
                doc_path = render_template(config.output.draft_output_path, template_context_doc)
            except TemplateError as e:
                console.print(f"[red]Error rendering draft_output_path for code-0: {e}[/red]")
                if debug:
                    raise
                sys.exit(1)
            doc_file = Path(doc_path)

            if debug:
                console.print("\n[bold cyan]Debug Mode: Documentation Release Notes[/bold cyan]")
                console.print("[dim]" + "=" * 60 + "[/dim]")
                console.print(f"[dim]Doc template configured:[/dim] {bool(config.output.pr_code.templates)}")
                console.print(f"[dim]Draft output path template:[/dim] {config.output.draft_output_path}")
                console.print(f"[dim]Resolved code-0 path:[/dim] {doc_path}")
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


def _find_existing_issue_auto(config: Config, github_client: GitHubClient, version: str, debug: bool = False) -> Optional[dict]:
    """Find existing issue automatically (non-interactive, picks first open issue)."""
    issues_repo = _get_issues_repo(config)
    # Search only for OPEN issues
    query = f"repo:{issues_repo} is:issue is:open {version} in:title"
    
    if debug:
        console.print(f"[dim]Searching for open issues matching version {version}...[/dim]")
    
    # Search for open issues matching the version
    # Safely iterate and collect up to 5 results
    issues = []
    try:
        search_results = github_client.gh.search_issues(query)
        for i, issue in enumerate(search_results):
            if i >= 5:
                break
            issues.append(issue)
    except Exception as e:
        if debug:
            console.print(f"[dim]Error searching for issues: {e}[/dim]")
        return None
    
    if not issues:
        if debug:
            console.print("[dim]No matching open issues found.[/dim]")
        return None
    
    # Automatically use the first open issue found
    selected = issues[0]
    
    if debug:
        console.print(f"[dim]Found open issue #{selected.number}: {selected.title}[/dim]")
    
    return {'number': str(selected.number), 'url': selected.html_url}
