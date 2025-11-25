"""Main CLI for the release tool."""

import sys
from pathlib import Path
from typing import Optional, List
from collections import defaultdict
import click
from rich.console import Console
from rich.table import Table

from .config import load_config, Config
from .db import Database
from .github_utils import GitHubClient
from .git_ops import GitOperations, get_release_commit_range, determine_release_branch_strategy
from .models import SemanticVersion
from .policies import (
    TicketExtractor,
    CommitConsolidator,
    ReleaseNoteGenerator,
    VersionGapChecker,
    PartialTicketMatch,
    PartialTicketReason
)
from .config import PolicyAction

console = Console()


@click.group()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    help='Path to configuration file'
)
@click.option(
    '--auto',
    is_flag=True,
    help='Run in non-interactive mode (auto-apply defaults, skip prompts)'
)
@click.pass_context
def cli(ctx, config: Optional[str], auto: bool):
    """Release tool for managing semantic versioned releases."""
    ctx.ensure_object(dict)
    ctx.obj['auto'] = auto
    # Don't load config for init-config and update-config commands
    if ctx.invoked_subcommand not in ['init-config', 'update-config']:
        try:
            ctx.obj['config'] = load_config(config, auto_upgrade=auto)
        except FileNotFoundError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)


@cli.command()
@click.argument('repository', required=False)
@click.option('--repo-path', type=click.Path(exists=True), help='Path to local git repository')
@click.pass_context
def sync(ctx, repository: Optional[str], repo_path: Optional[str]):
    """
    Sync repository data to local database.

    Fetches tickets, PRs, releases, and commits from GitHub and stores them locally.
    Uses highly parallelized fetching with incremental sync.
    """
    from .sync import SyncManager

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


@cli.command()
@click.argument('version', required=False)
@click.option('--from-version', help='Compare from this version (auto-detected if not specified)')
@click.option('--repo-path', type=click.Path(exists=True), help='Path to local git repository (defaults to synced repo)')
@click.option('--output', '-o', type=click.Path(), help='Output file for release notes')
@click.option('--dry-run', is_flag=True, help='Show what would be generated without creating files')
@click.option('--new-major', is_flag=True, help='Auto-bump major version (X.0.0)')
@click.option('--new-minor', is_flag=True, help='Auto-bump minor version (x.Y.0)')
@click.option('--new-patch', is_flag=True, help='Auto-bump patch version (x.y.Z)')
@click.option('--new-rc', is_flag=True, help='Create new RC version (auto-increments from existing RCs)')
@click.option('--format', type=click.Choice(['markdown', 'json'], case_sensitive=False), default='markdown', help='Output format (default: markdown)')
@click.option('--debug', is_flag=True, help='Show detailed pattern matching debug output')
@click.pass_context
def generate(ctx, version: Optional[str], from_version: Optional[str], repo_path: Optional[str],
             output: Optional[str], dry_run: bool, new_major: bool, new_minor: bool,
             new_patch: bool, new_rc: bool, format: str, debug: bool):
    """
    Generate release notes for a version.

    Analyzes commits between versions, consolidates by ticket, and generates
    formatted release notes.

    VERSION can be specified explicitly (e.g., "9.1.0") or auto-calculated using
    --new-major, --new-minor, --new-patch, or --new-rc options. Partial versions
    are supported (e.g., "9.2" + --new-patch creates 9.2.1).

    Examples:

      release-tool generate 9.1.0

      release-tool generate --new-minor

      release-tool generate --new-rc

      release-tool generate 9.1.0 --dry-run

      release-tool generate --new-patch --repo-path /custom/path

      release-tool generate 9.2 --new-patch
    """
    # Validate mutually exclusive version options
    version_flags = [new_major, new_minor, new_patch, new_rc]
    if sum(version_flags) > 1:
        console.print("[red]Error: Only one of --new-major, --new-minor, --new-patch, --new-rc can be specified[/red]")
        return

    if not version and not any(version_flags):
        console.print("[red]Error: VERSION argument or one of --new-major/--new-minor/--new-patch/--new-rc is required[/red]")
        return

    # Check if version is provided WITH a bump flag (partial version support)
    if version and any(version_flags):
        # Parse as partial version to use as base
        try:
            base_version = SemanticVersion.parse(version, allow_partial=True)
            console.print(f"[blue]Using base version: {base_version.to_string()}[/blue]")

            # Apply the bump
            if new_major:
                target_version = base_version.bump_major()
                console.print(f"[blue]Bumping major version → {target_version.to_string()}[/blue]")
            elif new_minor:
                target_version = base_version.bump_minor()
                console.print(f"[blue]Bumping minor version → {target_version.to_string()}[/blue]")
            elif new_patch:
                target_version = base_version.bump_patch()
                console.print(f"[blue]Bumping patch version → {target_version.to_string()}[/blue]")
            elif new_rc:
                # Find existing RCs for this base version and auto-increment
                import re
                rc_number = 0

                # Check database and Git for existing RCs of the same base version
                try:
                    # Get config from context
                    cfg = ctx.obj['config']

                    # First, try database (has all synced releases from GitHub)
                    db = Database(cfg.database.path)
                    db.connect()

                    # Get repository to get repo_id
                    repo_name = cfg.repository.code_repo
                    repo = db.get_repository(repo_name)

                    matching_rcs = []

                    if repo:
                        # Get all releases with version prefix matching our base version
                        version_prefix = f"{base_version.major}.{base_version.minor}.{base_version.patch}-rc"
                        all_releases = db.get_all_releases(
                            repo_id=repo.id,
                            version_prefix=version_prefix
                        )

                        for release in all_releases:
                            try:
                                v = SemanticVersion.parse(release.version)
                                if (v.major == base_version.major
                                    and v.minor == base_version.minor
                                    and v.patch == base_version.patch
                                    and v.prerelease and v.prerelease.startswith('rc.')):
                                    matching_rcs.append(v)
                            except ValueError:
                                continue

                    db.close()

                    # Also check Git tags in case there are local tags not synced
                    try:
                        git_ops_temp = GitOperations(cfg.get_code_repo_path())
                        git_versions = git_ops_temp.get_version_tags()
                        for v in git_versions:
                            if (v.major == base_version.major
                                and v.minor == base_version.minor
                                and v.patch == base_version.patch
                                and v.prerelease and v.prerelease.startswith('rc.')):
                                if v not in matching_rcs:
                                    matching_rcs.append(v)
                    except Exception:
                        pass

                    if matching_rcs:
                        # Extract RC numbers and find the highest
                        rc_numbers = []
                        for v in matching_rcs:
                            match = re.match(r'rc\.(\d+)', v.prerelease)
                            if match:
                                rc_numbers.append(int(match.group(1)))

                        if rc_numbers:
                            rc_number = max(rc_numbers) + 1
                except Exception as e:
                    # If we can't check existing RCs, start at 0
                    console.print(f"[yellow]Warning: Could not check existing RCs ({e}), starting at rc.0[/yellow]")

                target_version = base_version.bump_rc(rc_number)
                console.print(f"[blue]Creating RC version → {target_version.to_string()}[/blue]")

            version = target_version.to_string()
            # Skip the auto-calculation below
            version_flags = [False, False, False, False]
        except ValueError as e:
            console.print(f"[red]Error parsing version: {e}[/red]")
            return

    config: Config = ctx.obj['config']

    # Determine repo path (use synced repo as default)
    if not repo_path:
        repo_path = config.get_code_repo_path()
        console.print(f"[blue]Using synced repository: {repo_path}[/blue]")

    # Verify repo path exists
    from pathlib import Path
    if not Path(repo_path).exists():
        console.print(f"[red]Error: Repository path does not exist: {repo_path}[/red]")
        if not config.sync.code_repo_path:
            console.print("[yellow]Tip: Run 'release-tool sync' first to clone the repository[/yellow]")
        return

    try:
        # Initialize components
        db = Database(config.database.path)
        db.connect()

        try:
            # Get repository
            repo_name = config.repository.code_repo
            repo = db.get_repository(repo_name)
            if not repo:
                console.print(f"[yellow]Repository {repo_name} not found in database. Running sync...[/yellow]")
                github_client = GitHubClient(config)
                repo = github_client.get_repository_info(repo_name)
                repo.id = db.upsert_repository(repo)
            repo_id = repo.id

            # Initialize Git operations
            git_ops = GitOperations(repo_path)

            # Auto-calculate version if using bump options
            if any(version_flags):
                # For --new-patch, use latest final version (exclude RCs)
                # For other bumps, use latest version including RCs
                if new_patch:
                    latest_tag = git_ops.get_latest_tag(final_only=True)
                    if not latest_tag:
                        console.print("[red]Error: No final release tags found in repository. Cannot bump patch.[/red]")
                        console.print("[yellow]Tip: Create a final release first (e.g., 1.0.0) or specify version explicitly[/yellow]")
                        return
                else:
                    latest_tag = git_ops.get_latest_tag(final_only=False)
                    if not latest_tag:
                        console.print("[red]Error: No tags found in repository. Cannot auto-bump version.[/red]")
                        console.print("[yellow]Tip: Specify version explicitly or create an initial tag[/yellow]")
                        return

                base_version = SemanticVersion.parse(latest_tag)
                console.print(f"[blue]Latest version: {base_version.to_string()}[/blue]")

                if new_major:
                    target_version = base_version.bump_major()
                    console.print(f"[blue]Bumping major version → {target_version.to_string()}[/blue]")
                elif new_minor:
                    target_version = base_version.bump_minor()
                    console.print(f"[blue]Bumping minor version → {target_version.to_string()}[/blue]")
                elif new_patch:
                    target_version = base_version.bump_patch()
                    console.print(f"[blue]Bumping patch version → {target_version.to_string()}[/blue]")
                elif new_rc:
                    # Find the next RC number for this version
                    import re
                    rc_number = 0

                    # Check existing versions for RCs of the same base version
                    all_versions = git_ops.get_version_tags()
                    matching_rcs = [
                        v for v in all_versions
                        if v.major == base_version.major
                        and v.minor == base_version.minor
                        and v.patch == base_version.patch
                        and v.prerelease and v.prerelease.startswith('rc.')
                    ]

                    if matching_rcs:
                        # Extract RC numbers and find the highest
                        rc_numbers = []
                        for v in matching_rcs:
                            match = re.match(r'rc\.(\d+)', v.prerelease)
                            if match:
                                rc_numbers.append(int(match.group(1)))

                        if rc_numbers:
                            rc_number = max(rc_numbers) + 1

                    target_version = base_version.bump_rc(rc_number)
                    console.print(f"[blue]Creating RC version → {target_version.to_string()}[/blue]")

                version = target_version.to_string()
            else:
                # Parse explicitly provided version
                target_version = SemanticVersion.parse(version)

            if dry_run:
                console.print(f"[yellow]DRY RUN: Generating release notes for version {version}[/yellow]")
            else:
                console.print(f"[blue]Generating release notes for version {version}[/blue]")

            # Determine release branch strategy
            available_versions = git_ops.get_version_tags()
            release_branch, source_branch, should_create_branch = determine_release_branch_strategy(
                target_version,
                git_ops,
                available_versions,
                branch_template=config.branch_policy.release_branch_template,
                default_branch=config.branch_policy.default_branch,
                branch_from_previous=config.branch_policy.branch_from_previous_release
            )

            # Display branch information
            console.print(f"[blue]Release branch: {release_branch}[/blue]")
            if should_create_branch:
                console.print(f"[yellow]→ Branch does not exist, will create from: {source_branch}[/yellow]")
            else:
                console.print(f"[blue]→ Using existing branch (source: {source_branch})[/blue]")

            # Create branch if needed (unless dry-run)
            if should_create_branch and config.branch_policy.create_branches:
                if dry_run:
                    console.print(f"[yellow]DRY RUN: Would create branch '{release_branch}' from '{source_branch}'[/yellow]")
                else:
                    try:
                        # Ensure source branch exists locally
                        current_branch = git_ops.get_current_branch()

                        # Create the new release branch
                        git_ops.create_branch(release_branch, source_branch)
                        console.print(f"[green]✓ Created branch '{release_branch}' from '{source_branch}'[/green]")

                        # Optionally checkout the new branch
                        # git_ops.checkout_branch(release_branch)
                        # console.print(f"[green]✓ Checked out branch '{release_branch}'[/green]")
                    except ValueError as e:
                        console.print(f"[yellow]Warning: {e}[/yellow]")
                    except Exception as e:
                        console.print(f"[red]Error creating branch: {e}[/red]")
            elif should_create_branch:
                console.print(f"[yellow]→ Branch creation disabled in config[/yellow]")

            # Determine comparison version and get commits
            from_ver = SemanticVersion.parse(from_version) if from_version else None
            comparison_version, commits = get_release_commit_range(
                git_ops,
                target_version,
                from_ver
            )

            if comparison_version:
                console.print(f"[blue]Comparing {comparison_version.to_string()} → {version}[/blue]")

                # Check for version gaps
                gap_checker = VersionGapChecker(config)
                gap_checker.check_gap(comparison_version.to_string(), version)
            else:
                console.print(f"[blue]Generating notes for all commits up to {version}[/blue]")

            console.print(f"[blue]Found {len(commits)} commits[/blue]")

            # Convert git commits to our models and store them
            commit_models = []
            for git_commit in commits:
                commit_model = git_ops.commit_to_model(git_commit, repo_id)
                db.upsert_commit(commit_model)
                commit_models.append(commit_model)

            # Build PR map
            pr_map = {}
            for commit in commit_models:
                if commit.pr_number:
                    pr = db.get_pull_request(repo_id, commit.pr_number)
                    if pr:
                        pr_map[commit.pr_number] = pr

            # Extract tickets and consolidate
            extractor = TicketExtractor(config, debug=debug)
            consolidator = CommitConsolidator(config, extractor, debug=debug)
            consolidated_changes = consolidator.consolidate(commit_models, pr_map)

            console.print(f"[blue]Consolidated into {len(consolidated_changes)} changes[/blue]")

            # Handle missing tickets
            consolidator.handle_missing_tickets(consolidated_changes)

            # Load ticket information from database (offline) with partial detection
            # Tickets must be synced first using: release-tool sync
            partial_matches: List[PartialTicketMatch] = []

            # Get expected ticket repository IDs
            expected_repos = config.get_ticket_repos()
            expected_repo_ids = []
            for repo_name in expected_repos:
                repo = db.get_repository(repo_name)
                if repo:
                    expected_repo_ids.append(repo.id)

            for change in consolidated_changes:
                if change.ticket_key:
                    # Query ticket from database across all repos
                    ticket = db.get_ticket_by_key(change.ticket_key)

                    if not ticket:
                        # NOT FOUND - create partial match
                        extraction_source = _get_extraction_source(change)
                        partial = PartialTicketMatch(
                            ticket_key=change.ticket_key,
                            extracted_from=extraction_source,
                            match_type="not_found",
                            potential_reasons={
                                PartialTicketReason.OLDER_THAN_CUTOFF,
                                PartialTicketReason.TYPO,
                                PartialTicketReason.SYNC_NOT_RUN
                            }
                        )
                        partial_matches.append(partial)

                        if debug:
                            console.print(f"\n[yellow]⚠️  Ticket {change.ticket_key} not found in DB[/yellow]")

                    elif ticket.repo_id not in expected_repo_ids:
                        # DIFFERENT REPO - create partial match
                        found_repo = db.get_repository_by_id(ticket.repo_id)
                        extraction_source = _get_extraction_source(change)
                        partial = PartialTicketMatch(
                            ticket_key=change.ticket_key,
                            extracted_from=extraction_source,
                            match_type="different_repo",
                            found_in_repo=found_repo.full_name if found_repo else "unknown",
                            ticket_url=ticket.url,
                            potential_reasons={
                                PartialTicketReason.REPO_CONFIG_MISMATCH,
                                PartialTicketReason.WRONG_TICKET_REPOS
                            }
                        )
                        partial_matches.append(partial)

                        if debug:
                            console.print(f"\n[yellow]⚠️  Ticket {change.ticket_key} in different repo: {found_repo.full_name if found_repo else 'unknown'}[/yellow]")

                    else:
                        # Found in correct repo
                        if debug:
                            console.print(f"\n[dim]📋 Found ticket in DB: #{ticket.number} - {ticket.title}[/dim]")

                    change.ticket = ticket

            # Apply partial ticket policy
            _handle_partial_tickets(partial_matches, config, debug)

            # Generate release notes
            note_generator = ReleaseNoteGenerator(config)
            release_notes = []
            for change in consolidated_changes:
                note = note_generator.create_release_note(change, change.ticket)
                release_notes.append(note)

            # Group and format
            grouped_notes = note_generator.group_by_category(release_notes)

            # Format output based on format option
            if format == 'json':
                import json
                # Convert to JSON
                json_output = {
                    'version': version,
                    'from_version': comparison_version.to_string() if comparison_version else None,
                    'num_commits': len(commits),
                    'num_changes': len(consolidated_changes),
                    'categories': {}
                }
                for category, notes in grouped_notes.items():
                    json_output['categories'][category] = [
                        {
                            'title': note.title,
                            'ticket_key': note.ticket_key,
                            'description': note.description,
                            'labels': note.labels
                        }
                        for note in notes
                    ]
                formatted_output = json.dumps(json_output, indent=2)
            else:
                # Format markdown with media processing if output path is available
                formatted_output = note_generator.format_markdown(
                    grouped_notes,
                    version,
                    output_path=output
                )

            # Output handling
            if dry_run:
                console.print(f"\n[yellow]{'='*80}[/yellow]")
                console.print(f"[yellow]DRY RUN - Release notes for {version}:[/yellow]")
                console.print(f"[yellow]{'='*80}[/yellow]\n")
                console.print(formatted_output)
                console.print(f"\n[yellow]{'='*80}[/yellow]")
                console.print(f"[yellow]DRY RUN complete. No files were created.[/yellow]")
                console.print(f"[yellow]{'='*80}[/yellow]\n")
            else:
                # Determine output path: use provided path or default to draft cache
                if not output:
                    # Build default draft path from config template
                    draft_template = config.output.draft_output_path
                    output = draft_template.format(
                        repo=repo_name.replace('/', '-'),  # Sanitize repo name for filesystem
                        version=version,
                        major=target_version.major,
                        minor=target_version.minor,
                        patch=target_version.patch
                    )

                output_path_obj = Path(output)
                output_path_obj.parent.mkdir(parents=True, exist_ok=True)
                output_path_obj.write_text(formatted_output)
                console.print(f"[green]✓ Release notes written to:[/green]")
                console.print(f"[green]  {output_path_obj.absolute()}[/green]")
                console.print(f"[blue]→ Review and edit the file, then use 'release-tool publish {version} -f {output}' to upload to GitHub[/blue]")

        finally:
            db.close()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if '--debug' in sys.argv:
            raise
        sys.exit(1)


def _get_extraction_source(change, commits_map=None, prs_map=None):
    """
    Get human-readable description of where a ticket was extracted from.

    Args:
        change: ConsolidatedChange object
        commits_map: Optional dict mapping sha to commit for lookups
        prs_map: Optional dict mapping pr_number to PR for lookups

    Returns:
        String like "branch feat/meta-8624/main, pattern #1"
    """
    # Try to get from PR first (most reliable)
    if change.prs and len(change.prs) > 0:
        pr = change.prs[0]
        if pr.head_branch:
            return f"branch {pr.head_branch}, PR #{pr.number}"
        return f"PR #{pr.number}"

    # Fall back to commit info
    if change.commits and len(change.commits) > 0:
        commit = change.commits[0]
        return f"commit {commit.sha[:7]}"

    return "unknown source"


def _handle_partial_tickets(partials: List[PartialTicketMatch], config, debug: bool):
    """
    Handle partial ticket matches based on policy configuration.

    Args:
        partials: List of PartialTicketMatch objects
        config: Config object with ticket_policy.partial_ticket_action
        debug: Whether debug mode is enabled

    Raises:
        RuntimeError: If policy is ERROR and partials exist
    """
    if not partials:
        return

    action = config.ticket_policy.partial_ticket_action

    if action == PolicyAction.IGNORE:
        return

    # Group by type
    not_found = [p for p in partials if p.match_type == "not_found"]
    different_repo = [p for p in partials if p.match_type == "different_repo"]

    # Build warning message
    msg_lines = []
    msg_lines.append("")
    msg_lines.append(f"[yellow]⚠️  Found {len(partials)} partial ticket match(es)[/yellow]")
    msg_lines.append("")

    # Handle different_repo partials
    if different_repo:
        msg_lines.append(f"[cyan]Tickets in different repository ({len(different_repo)}):[/cyan]")

        # Group tickets by reason
        tickets_by_reason = defaultdict(list)
        for p in different_repo:
            for reason in p.potential_reasons:
                tickets_by_reason[reason].append(p)

        # Show reasons with associated tickets
        msg_lines.append(f"  [dim]This might be because of:[/dim]")
        for reason, tickets in tickets_by_reason.items():
            ticket_keys = [p.ticket_key for p in tickets]
            msg_lines.append(f"    • {reason.description}")
            msg_lines.append(f"      [dim]Tickets:[/dim] {', '.join(ticket_keys)}")

        msg_lines.append("")
        msg_lines.append("  [dim]Details:[/dim]")
        for p in different_repo:
            msg_lines.append(f"    • [bold]{p.ticket_key}[/bold] (from {p.extracted_from})")
            if p.found_in_repo:
                msg_lines.append(f"      [dim]Found in:[/dim] {p.found_in_repo}")
            if p.ticket_url:
                msg_lines.append(f"      [dim]URL:[/dim] {p.ticket_url}")
        msg_lines.append("")

    # Handle not_found partials
    if not_found:
        msg_lines.append(f"[cyan]Tickets not found in database ({len(not_found)}):[/cyan]")

        # Group tickets by reason
        tickets_by_reason = defaultdict(list)
        for p in not_found:
            for reason in p.potential_reasons:
                tickets_by_reason[reason].append(p)

        # Show reasons with associated tickets
        msg_lines.append(f"  [dim]This might be because of:[/dim]")
        for reason, tickets in tickets_by_reason.items():
            ticket_keys = [p.ticket_key for p in tickets]
            msg_lines.append(f"    • {reason.description}")
            msg_lines.append(f"      [dim]Tickets:[/dim] {', '.join(ticket_keys)}")

        msg_lines.append("")
        msg_lines.append("  [dim]Details:[/dim]")
        for p in not_found:
            msg_lines.append(f"    • [bold]{p.ticket_key}[/bold] (from {p.extracted_from})")
        msg_lines.append("")

    msg_lines.append("[dim]To resolve:[/dim]")
    msg_lines.append("  1. Run [bold]'release-tool sync'[/bold] to fetch latest tickets")
    msg_lines.append("  2. Check [bold]repository.ticket_repos[/bold] in config")
    msg_lines.append("  3. Verify ticket numbers in branches/PRs")
    msg_lines.append("")

    console.print("\n".join(msg_lines))

    if action == PolicyAction.ERROR:
        raise RuntimeError(f"Partial ticket matches found ({len(partials)} total). Policy: error")


@cli.command()
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


@cli.command()
@click.argument('repository', required=False)
@click.option('--limit', '-n', type=int, default=10, help='Number of releases to show (default: 10, use 0 for all)')
@click.option('--version', '-v', type=str, help='Filter by version prefix (e.g., "9" for 9.x.x, "9.3" for 9.3.x)')
@click.option('--type', '-t', multiple=True, type=click.Choice(['final', 'rc', 'beta', 'alpha'], case_sensitive=False), help='Release types to include (can be specified multiple times)')
@click.option('--after', type=str, help='Only show releases published after this date (YYYY-MM-DD)')
@click.option('--before', type=str, help='Only show releases published before this date (YYYY-MM-DD)')
@click.pass_context
def list_releases(ctx, repository: Optional[str], limit: int, version: Optional[str], type: tuple, after: Optional[str], before: Optional[str]):
    """
    List releases in the database.

    By default shows the last 10 releases. Use --limit 0 to show all releases.

    Examples:

      release-tool list-releases --version "9"              # All 9.x.x releases

      release-tool list-releases --version "9.3"            # All 9.3.x releases

      release-tool list-releases --type final               # Only final releases

      release-tool list-releases --type final --type rc     # Finals and RCs

      release-tool list-releases --after 2024-01-01         # Since 2024

      release-tool list-releases --before 2024-06-01        # Before June 2024
    """
    config: Config = ctx.obj['config']
    repo_name = repository or config.repository.code_repo

    from datetime import datetime

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
            console.print(f"[red]Repository {repo_name} not found. Run 'sync' first.[/red]")
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
            version = SemanticVersion.parse(release.version)
            rel_type = "RC" if not version.is_final() else "Final"
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


@cli.command('init-config')
def init_config():
    """Create an example configuration file."""
    # Load template from config_template.toml
    template_path = Path(__file__).parent / "config_template.toml"
    try:
        example_config = template_path.read_text(encoding='utf-8')
    except Exception as e:
        console.print(f"[red]Error loading config template: {e}[/red]")
        console.print("[yellow]Falling back to minimal config...[/yellow]")
        example_config = """
config_version = "1.1"

# =============================================================================
# Release Tool Configuration
# =============================================================================
# This file controls how the release tool generates release notes by managing:
# - Repository information and GitHub integration
# - Ticket extraction and consolidation policies
# - Version comparison and gap detection
# - Release note categorization and formatting
# - Output destinations (file, GitHub release, PR)

# =============================================================================
# Repository Configuration
# =============================================================================
[repository]
# code_repo (REQUIRED): The GitHub repository containing the code
# Format: "owner/repo" (e.g., "sequentech/voting-booth")
code_repo = "sequentech/step"

# ticket_repos: List of repositories where tickets/issues are tracked
# If empty, uses code_repo for tickets as well
# This is useful when tickets are tracked in different repos than the code
# Default: [] (uses code_repo)
ticket_repos = ["sequentech/meta"]

# default_branch: The main branch of the repository
# Default: "main"
# Common values: "main", "master", "develop"
default_branch = "main"

# =============================================================================
# GitHub API Configuration
# =============================================================================
[github]
# token: GitHub Personal Access Token for API authentication
# RECOMMENDED: Use GITHUB_TOKEN environment variable instead of storing here
# The token needs the following permissions:
#   - repo (for accessing repositories, PRs, issues)
#   - write:packages (if creating releases)
# How to create: https://github.com/settings/tokens
# Default: reads from GITHUB_TOKEN environment variable
# token = "ghp_..."

# api_url: GitHub API base URL
# Change this only if using GitHub Enterprise Server
# Default: "https://api.github.com"
# For GitHub Enterprise: "https://github.yourcompany.com/api/v3"
api_url = "https://api.github.com"

# =============================================================================
# Database Configuration
# =============================================================================
[database]
# path: Location of the SQLite database file for caching GitHub data
# The database stores PRs, commits, tickets, and releases to minimize API calls
# Relative paths are relative to the current working directory
# Default: "release_tool.db"
path = "release_tool.db"

# =============================================================================
# Sync Configuration
# =============================================================================
[sync]
# cutoff_date: Only fetch tickets/PRs created after this date (ISO format: YYYY-MM-DD)
# This limits historical data fetching and speeds up initial sync
# Example: "2024-01-01" to only fetch data from 2024 onwards
# Default: null (fetch all historical data)
cutoff_date = "2025-01-01"

# parallel_workers: Number of parallel workers for GitHub API calls
# Higher values = faster sync, but may hit rate limits more quickly
# Recommended: 5-20 depending on your API rate limit
# Default: 10
parallel_workers = 10

# clone_code_repo: Whether to clone the code repository locally for offline operation
# When true, the generate-notes command can work without internet access
# Default: true
clone_code_repo = true

# code_repo_path: Local path where to clone/sync the code repository
# If not specified, defaults to .release_tool_cache/{repo_name}
# Example: "/tmp/release_tool_repos/voting-booth"
# Default: null (uses .release_tool_cache/{repo_name})
# code_repo_path = "/path/to/local/repo"

# show_progress: Show progress updates during sync
# When true, displays messages like "syncing 13 / 156 tickets (10% done)"
# Default: true
show_progress = true

# =============================================================================
# Ticket Extraction and Consolidation Policy
# =============================================================================
# patterns: Ordered list of ticket extraction patterns
# Each pattern is associated with a specific extraction strategy (where to look)
# and uses Python regex with NAMED CAPTURE GROUPS (use "ticket" group for the ID)
#
# Patterns are tried in ORDER (by the "order" field). First match wins.
# Lower order numbers = higher priority. You can reorder by changing the numbers.
# TIP: Put more specific/reliable patterns first (lower order), generic ones last
#
# Available strategies:
#   - "branch_name": Extract from PR branch name (e.g., feat/meta-123/main)
#   - "pr_body": Extract from PR description text
#   - "pr_title": Extract from PR title
#   - "commit_message": Extract from commit message text
#
# Pattern structure:
#   [[ticket_policy.patterns]]
#   order = 1              # Priority (lower = tried first)
#   strategy = "branch_name"  # Where to look
#   pattern = "regex_here"    # What to match (use (?P<ticket>\\\\d+) for ID)
#   description = "explanation"  # Optional: what this pattern matches

# ORDER 1: Branch name (most reliable, structured format)
# Matches: feat/meta-123/main, fix/repo-456.whatever/develop
# Format: <type>/<repo>-<ticket_number>[.optional]/<target_branch>
[[ticket_policy.patterns]]
order = 1
strategy = "branch_name"
pattern = "/(?P<repo>\\\\w+)-(?P<ticket>\\\\d+)"
description = "Branch name format: type/repo-123/target"

# ORDER 2: Parent issue URL in PR body (backup policy)
# Matches: "Parent issue: https://github.com/owner/repo/issues/999"
# Use this when the branch name doesn't follow convention
[[ticket_policy.patterns]]
order = 2
strategy = "pr_body"
pattern = "Parent issue:.*?/issues/(?P<ticket>\\\\d+)"
description = "Parent issue URL in PR description"

# ORDER 3: GitHub issue reference in PR title
# Matches: "#123" in the PR title
[[ticket_policy.patterns]]
order = 3
strategy = "pr_title"
pattern = "#(?P<ticket>\\\\d+)"
description = "GitHub issue reference (#123) in PR title"

[ticket_policy]
# no_ticket_action: What to do when a commit/PR has no associated ticket
# Valid values:
#   - "ignore": Silently skip the warning, include in release notes
#   - "warn": Print a warning but continue (RECOMMENDED for most teams)
#   - "error": Stop the release note generation with an error
# Default: "warn"
# Use "error" for strict ticket tracking, "warn" for flexibility
no_ticket_action = "warn"

# unclosed_ticket_action: What to do with tickets that are still open
# Valid values:
#   - "ignore": Include open tickets in release notes without warning
#   - "warn": Print a warning but include them (RECOMMENDED)
#   - "error": Stop if any tickets are still open
# Default: "warn"
unclosed_ticket_action = "warn"

# consolidation_enabled: Group multiple commits by their parent ticket
# When true: Commits with the same ticket (e.g., TICKET-123) are grouped
#            into a single release note entry
# When false: Each commit appears as a separate entry in release notes
# Default: true
# RECOMMENDED: true (makes release notes more concise and readable)
consolidation_enabled = true

# description_section_regex: Regex to extract description from ticket body
# Uses Python regex with capturing group (group 1 is extracted)
# Looks for sections like "## Description" or "## Summary" in ticket text
# The tool gracefully handles tickets without description sections
# Default: r'(?:## Description|## Summary)\\n(.*?)(?=\\n##|\\Z)'
# Set to empty string "" to disable description extraction
# NOTE: In TOML, backslashes must be doubled: \\n becomes \\\\n, \\Z becomes \\\\Z
description_section_regex = "(?:## Description|## Summary)\\\\n(.*?)(?=\\\\n##|\\\\Z)"

# migration_section_regex: Regex to extract migration notes from ticket body
# Useful for database migrations, breaking changes, upgrade steps
# Looks for sections like "## Migration" or "## Migration Notes"
# The tool gracefully handles tickets without migration sections
# Default: r'(?:## Migration|## Migration Notes)\\n(.*?)(?=\\n##|\\Z)'
# Set to empty string "" to disable migration notes extraction
# NOTE: In TOML, backslashes must be doubled: \\n becomes \\\\n, \\Z becomes \\\\Z
migration_section_regex = "(?:## Migration|## Migration Notes)\\\\n(.*?)(?=\\\\n##|\\\\Z)"

# =============================================================================
# Version Comparison and Gap Detection Policy
# =============================================================================
[version_policy]
# gap_detection: Check for missing versions between releases
# Detects gaps like 1.0.0 → 1.2.0 (missing 1.1.0)
# Valid values:
#   - "ignore": Don't check for version gaps
#   - "warn": Print a warning if gaps detected (RECOMMENDED)
#   - "error": Stop the process if gaps are detected
# Default: "warn"
gap_detection = "warn"

# tag_prefix: Prefix used for version tags in Git
# The tool will look for tags like "v1.0.0" if prefix is "v"
# Common values: "v", "release-", "" (empty for no prefix)
# Default: "v"
tag_prefix = "v"

# =============================================================================
# Branch Management Policy
# =============================================================================
# Controls how release branches are created and managed
[branch_policy]
# release_branch_template: Template for release branch names
# Use {major}, {minor}, {patch} as placeholders
# Examples:
#   - "release/{major}.{minor}" → "release/9.1"
#   - "rel-{major}.{minor}.x" → "rel-9.1.x"
#   - "v{major}.{minor}" → "v9.1"
# Default: "release/{major}.{minor}"
release_branch_template = "release/{major}.{minor}"

# default_branch: The default branch for new major versions
# New major versions (e.g., 9.0.0 when coming from 8.x.x) will branch from this
# Common values: "main", "master", "develop"
# Default: "main"
default_branch = "main"

# create_branches: Automatically create release branches if they don't exist
# When true, the tool will create a new release branch automatically
# When false, you must create branches manually
# Default: true
create_branches = true

# branch_from_previous_release: Branch new minor versions from previous release
# Controls the branching strategy for new minor versions:
#   - true:  9.1.0 branches from release/9.0 (if it exists)
#   - false: 9.1.0 branches from main (default_branch)
# This enables hotfix workflows where release branches persist
# Default: true
branch_from_previous_release = true

# =============================================================================
# Release Notes Categorization
# =============================================================================
# Categories group release notes by the labels on tickets/PRs
# Each category can match multiple labels, and has a display order
#
# Label Matching with Source Prefixes:
# You can specify where labels should match from using prefixes:
#   - "pr:label_name"     = Only match this label from Pull Requests
#   - "ticket:label_name" = Only match this label from Tickets/Issues
#   - "label_name"        = Match from EITHER PRs or tickets (default)
#
# This is useful when PRs and tickets use the same label names differently.
# For example:
#   - PRs might use "bug" for any bug-related code change
#   - Tickets might use "bug" only for confirmed bugs needing fixes
#   - You can categorize them separately: ["pr:bug"] vs ["ticket:bug"]
#
# Category structure:
#   [[release_notes.categories]]
#   name = "Display Name"       # Shown in the release notes
#   labels = ["label1", "pr:label2", "ticket:label3"]  # With optional prefixes
#   order = 1                   # Display order (lower numbers appear first)

[[release_notes.categories]]
name = "💥 Breaking Changes"
labels = ["breaking-change", "breaking"]
order = 1
alias = "breaking"

[[release_notes.categories]]
name = "🚀 Features"
labels = ["feature", "enhancement", "feat"]
order = 2
alias = "features"

[[release_notes.categories]]
name = "🛠 Bug Fixes"
labels = ["bug", "fix", "bugfix", "hotfix"]
order = 3
alias = "bugfixes"

[[release_notes.categories]]
name = "📖 Documentation"
labels = ["docs", "documentation"]
order = 4
alias = "docs"

[[release_notes.categories]]
name = "🛡 Security Updates"
labels = ["security"]
order = 5
alias = "security"

[[release_notes.categories]]
name = "Other Changes"
labels = []
order = 99
alias = "other"

# =============================================================================
# Release Notes Formatting and Content
# =============================================================================
[release_notes]
# excluded_labels: Skip tickets/PRs with these labels from release notes
# Useful for internal changes, CI updates, etc.
# Default: ["skip-changelog", "internal"]
excluded_labels = ["skip-changelog", "internal", "wip", "do-not-merge"]

# title_template: Jinja2 template for the release notes title
# Available variables:
#   - {{ version }}: The version being released (e.g., "1.2.3")
# Default: "Release {{ version }}"
title_template = "Release {{ version }}"

# entry_template: Jinja2 template for each individual release note entry
# This is a POWERFUL template that lets you customize exactly how each change
# appears in the release notes. You can use Jinja2 syntax including conditionals,
# loops, filters, and all available variables.
#
# IMPORTANT: HTML-like behavior for whitespace and line breaks
#   - Multiple spaces/tabs are collapsed into a single space (like HTML)
#   - New lines in the template are ignored unless you use <br> or <br/>
#   - Use <br> or <br/> for explicit line breaks in the output
#   - This allows multi-line templates for readability while controlling output
#
# Available variables for each entry:
#   - {{ title }}           : The title/summary of the change (string)
#                             Example: "Fix authentication bug in login flow"
#   - {{ url }}             : Link to the ticket or PR (string or None)
#                             Example: "https://github.com/owner/repo/issues/123"
#   - {{ pr_numbers }}      : List of related PR numbers (list of int)
#                             Example: [123, 124]
#   - {{ authors }}         : List of author objects (list of dict)
#                             Each author is a dict with comprehensive information:
#                             - name: Git author name (e.g., "John Doe")
#                             - email: Git author email (e.g., "john@example.com")
#                             - username: GitHub login (e.g., "johndoe")
#                             - github_id: GitHub user ID (e.g., 12345)
#                             - display_name: GitHub display name
#                             - avatar_url: Profile picture URL
#                             - profile_url: GitHub profile URL
#                             - company: Company name
#                             - location: Location
#                             - bio: Bio text
#                             - blog: Blog URL
#                             - user_type: "User", "Bot", or "Organization"
#                             - identifier: Best identifier (username > name > email)
#                             - mention: @mention format (e.g., "@johndoe")
#                             - full_display_name: Best display name
#   - {{ description }}     : Extracted description text (string or None)
#                             Example: "This fixes the login flow by..."
#   - {{ migration_notes }} : Extracted migration notes (string or None)
#                             Example: "Run: python manage.py migrate"
#   - {{ labels }}          : List of label names (list of string)
#                             Example: ["bug", "critical", "security"]
#   - {{ ticket_key }}      : Ticket identifier (string or None)
#                             Example: "#123" or "JIRA-456"
#   - {{ category }}        : Assigned category name (string or None)
#                             Example: "Bug Fixes"
#   - {{ commit_shas }}     : List of commit SHA hashes (list of string)
#                             Example: ["a1b2c3d", "e4f5g6h"]
#
# Jinja2 syntax examples:
#   - Conditionals: {% if url %}...{% endif %}
#   - Loops: {% for author in authors %}@{{ author.username }}{% endfor %}
#   - Filters: {{ description|truncate(100) }}
#   - Boolean check: {% if pr_numbers %}(#{{ pr_numbers[0] }}){% endif %}
#   - Line breaks: Use <br> or <br/> for new lines in output
#   - Author fields: {{ author.username }}, {{ author.name }}, {{ author.mention }}
#
# Template examples:
#   1. Minimal (single line):
#      entry_template = "- {{ title }}"
#
#   2. With PR link (single line):
#      entry_template = "- {{ title }}{% if url %} ([#{{ pr_numbers[0] }}]({{ url }})){% endif %}"
#
#   3. With GitHub @mentions (uses author.mention for smart @username or name):
#      entry_template = '''- {{ title }}
#      {% if url %}([#{{ pr_numbers[0] }}]({{ url }})){% endif %}
#      {% if authors %}<br>by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}'''
#
#   4. With author names and emails:
#      entry_template = '''- {{ title }}
#      {% if authors %}<br>by {% for author in authors %}{{ author.name }} &lt;{{ author.email }}&gt;{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}'''
#
#   5. With author avatars and profile links (for markdown/HTML):
#      entry_template = '''- {{ title }}
#      {% if authors %}<br>by {% for author in authors %}<a href="{{ author.profile_url }}"><img src="{{ author.avatar_url }}" width="20"/> {{ author.display_name }}</a>{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}'''
#
#   6. Complex multi-line with labels, migration notes, and rich authors:
#      entry_template = '''- {{ title }}
#      {% if url %}([#{{ pr_numbers[0] }}]({{ url }})){% endif %}
#      {% if labels %} `{{ labels|join('` `') }}`{% endif %}
#      {% if authors %}<br>Contributors: {% for author in authors %}@{{ author.username or author.name }}{% if author.company %} ({{ author.company }}){% endif %}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
#      {% if migration_notes %}<br>  **Migration:** {{ migration_notes }}{% endif %}'''
#
# Default: Multi-line template with title, URL, and author mentions
# The whitespace will collapse, <br> tags not used in default for single-line output
# Uses author.mention which gives @username if available, otherwise falls back to name
entry_template = '''- {{ title }}
  {% if url %}{{ url }}{% endif %}
  {% if authors %}
  by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}
  {% endif %}'''

# output_template: MASTER Jinja2 template for the entire release notes output
# This is an ADVANCED feature that gives you complete control over the release
# notes structure. When set, this template replaces the default category-based
# layout and lets you design your own custom format.
#
# WHEN TO USE:
#   - You want a custom layout (e.g., flat list, grouped by type, etc.)
#   - You need to iterate over migrations or descriptions across all tickets
#   - You want full control over the output structure
#
# IMPORTANT: HTML-like behavior for whitespace (same as entry_template)
#   - Multiple spaces collapse to single space
#   - Line breaks: Use <br> or <br/> for new lines in output
#
# Available variables:
#   - {{ version }}      : Version string (e.g., "1.2.3")
#   - {{ title }}        : Rendered release title (from title_template)
#   - {{ categories }}   : List of category dicts with 'name' and 'notes'
#   - {{ all_notes }}    : Flat list of all note dicts (across categories)
#   - {{ render_entry(note) }}: Function to render a note using entry_template
#
# Each note dict contains:
#   - title, url, pr_numbers, commit_shas, labels, ticket_key, category
#   - description, migration_notes (processed, may be None)
#   - authors (list of author dicts with all fields)
#
# Template examples:
#
#   1. Default category-based layout (equivalent to not setting output_template):
#      output_template = '''# {{ title }}
#
#      {% for category in categories %}
#      ## {{ category.name }}
#      {% for note in category.notes %}
#      {{ render_entry(note) }}
#      {% endfor %}
#      {% endfor %}'''
#
#   2. Flat list without categories:
#      output_template = '''# {{ title }}
#
#      {% for note in all_notes %}
#      {{ render_entry(note) }}
#      {% endfor %}'''
#
#   3. Custom layout with migrations section:
#      output_template = '''# {{ title }}
#
#      ## Changes
#      {% for note in all_notes %}
#      {{ render_entry(note) }}
#      {% endfor %}
#
#      ## Migration Notes
#      {% for note in all_notes %}
#      {% if note.migration_notes %}
#      ### {{ note.title }}
#      {{ note.migration_notes }}
#      {% endif %}
#      {% endfor %}'''
#
#   4. Grouped by ticket with full descriptions:
#      output_template = '''# {{ title }}
#
#      {% for note in all_notes %}
#      ## {{ note.title }}
#      {% if note.description %}
#      {{ note.description }}
#      {% endif %}
#      {% if note.url %}
#      **Pull Request:** [#{{ note.pr_numbers[0] }}]({{ note.url }})
#      {% endif %}
#      {% if note.authors %}
#      **Authors:** {% for author in note.authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}
#      {% endif %}
#      {% if note.migration_notes %}
#      **Migration:** {{ note.migration_notes }}
#      {% endif %}
#      {% endfor %}'''
#
#   5. Custom grouping with manual entry rendering:
#      output_template = '''# {{ title }}
#
#      ## Features & Fixes
#      {% for category in categories %}
#      {% if category.name in ["Features", "Bug Fixes"] %}
#      ### {{ category.name }}
#      {% for note in category.notes %}
#      {{ render_entry(note) }}
#      {% endfor %}
#      {% endif %}
#      {% endfor %}
#
#      ## Other Changes
#      {% for category in categories %}
#      {% if category.name not in ["Features", "Bug Fixes"] %}
#      {% for note in category.notes %}
#      - {{ note.title }}{% if note.url %} ([#{{ note.pr_numbers[0] }}]({{ note.url }})){% endif %}
#      {% endfor %}
#      {% endif %}
#      {% endfor %}'''
#
# Default: Comprehensive template with breaking changes, migrations, descriptions, and categorized changes
output_template = '''# {{ title }}

{% set breaking_with_desc = all_notes|selectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}
{% if breaking_with_desc|length > 0 %}
## 💥 Breaking Changes
{% for note in breaking_with_desc %}
### {{ note.title }}
{{ note.description }}
{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}
{% set migration_notes = all_notes|selectattr('migration_notes')|list %}
{% if migration_notes|length > 0 %}
## 🔄 Migrations
{% for note in migration_notes %}
### {{ note.title }}
{{ note.migration_notes }}
{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}
{% set non_breaking_with_desc = all_notes|rejectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}
{% if non_breaking_with_desc|length > 0 %}
## 📝 Highlights
{% for note in non_breaking_with_desc %}
### {{ note.title }}
{{ note.description }}
{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}
## 📋 All Changes
{% for category in categories %}
### {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}

{% endfor %}'''

# =============================================================================
# Output Configuration
# =============================================================================
[output]
# output_path: Path template for release notes file
# This file will only be created/updated if you use the CLI --output flag
# or if create_pr is enabled (requires a file to be created for the PR)
#
# Available variables for path substitution:
#   - {version}: Full version string (e.g., "1.2.3", "2.0.0-rc.1")
#   - {major}: Major version number only (e.g., "1")
#   - {minor}: Minor version number only (e.g., "2")
#   - {patch}: Patch version number only (e.g., "3")
#
# Path template examples:
#   - "CHANGELOG.md": Single changelog file (appends/overwrites)
#   - "docs/releases/{version}.md": Separate file per version
#   - "releases/{major}.{minor}/{patch}.md": Organized by major.minor
#   - "docs/{major}.x.md": One file per major version
#   - "website/releases/v{version}.md": With prefix
#
# Default: "docs/releases/{version}.md"
output_path = "docs/docusaurus/docs/releases/release-{major}.{minor}/release-{major}.{minor}.{patch}.md"

# draft_output_path: Path template for draft release notes (generate command)
# This is where 'generate' command saves files by default (when --output not specified)
# Files are saved here for review/editing before publishing to GitHub
#
# Available variables:
#   - {repo}: Repository name (e.g., "owner-repo")
#   - {version}: Full version string
#   - {major}: Major version number
#   - {minor}: Minor version number
#   - {patch}: Patch version number
#
# Examples:
#   - ".release_tool_cache/draft-releases/{repo}/{version}.md": Organized by repo and version
#   - "drafts/{major}.{minor}.{patch}.md": Simple draft folder
#   - "/tmp/releases/{repo}-{version}.md": Temporary location
#
# Default: ".release_tool_cache/draft-releases/{repo}/{version}.md"
draft_output_path = ".release_tool_cache/draft-releases/{repo}/{version}.md"

# assets_path: Path template for downloaded media assets (images, videos)
# Images and videos referenced in ticket descriptions will be downloaded here
# and references will be updated to use local paths in the release notes
# This is useful for Docusaurus and other static site generators
#
# Available variables (same as output_path):
#   - {version}: Full version string
#   - {major}: Major version number
#   - {minor}: Minor version number
#   - {patch}: Patch version number
#
# Path must be relative to output_path for correct markdown references
# Examples:
#   - "docs/releases/assets/{version}": Organized by version
#   - "static/img/releases/{major}.{minor}": Shared across patches
#   - "assets/{version}": Simple structure
#
# Default: "docs/releases/assets/{version}"
assets_path = "docs/docusaurus/docs/releases/release-{major}.{minor}/assets"

# download_media: Download images and videos from ticket descriptions
# When true: Downloads media files and updates references to local paths
# When false: Keeps original URLs in release notes
# Default: true
# RECOMMENDED: true for static sites (Docusaurus), false for GitHub releases
download_media = false

# create_github_release: Automatically create a GitHub release
# When true: Uploads release notes to GitHub Releases
# When false: Only generates markdown (no upload)
# Default: false
# SECURITY: Requires GitHub token with repo write permissions
create_github_release = false

# create_pr: Automatically create a PR with the release notes file
# When true: Creates a PR to add/update the release notes file
# When false: No PR is created
# Requires: output_path to be configured
# Default: false
create_pr = false

# =============================================================================
# Pull Request Templates (for create_pr)
# =============================================================================
[output.pr_templates]
# branch_template: Template for the PR branch name
# Available variables:
#   - {version}: Full version string (e.g., "1.2.3")
#   - {major}, {minor}, {patch}: Version components
#
# Examples:
#   - "release-notes-{version}": Default format
#   - "docs/release-{major}.{minor}.{patch}": Structured branch
#   - "chore/update-changelog-{version}": With prefix
#
# Default: "release-notes-{version}"
branch_template = "release-notes-{version}"

# title_template: Template for the PR title
# Available variables:
#   - {version}: Full version string
#   - {major}, {minor}, {patch}: Version components
#   - {num_changes}: Number of changes in release notes (integer)
#   - {num_categories}: Number of non-empty categories (integer)
#
# Examples:
#   - "Release notes for {version}": Simple title
#   - "docs: Add release notes for v{version}": Conventional commits
#   - "Release {version} with {num_changes} changes": With counts
#
# Default: "Release notes for {version}"
title_template = "Release notes for {version}"

# body_template: Template for the PR description
# Available variables (same as title_template):
#   - {version}: Full version string
#   - {major}, {minor}, {patch}: Version components
#   - {num_changes}: Number of changes
#   - {num_categories}: Number of categories
#
# Examples:
#   - Simple:
#     body_template = "Automated release notes for version {version}."
#
#   - Detailed (DEFAULT) - use triple quotes for multi-line:
#     body_template = '''Automated release notes for version {version}.
#
#     ## Summary
#     This PR adds release notes for {version} with {num_changes} changes across {num_categories} categories.'''
#
# Default: Multi-line summary with change counts (TOML multi-line string)
body_template = '''Automated release notes for version {version}.

## Summary
This PR adds release notes for {version} with {num_changes} changes across {num_categories} categories.'''

# pr_target_branch: Target branch for the release notes PR
# The branch where the PR will be merged
# Default: "main"
# Common values: "main", "master", "develop"
pr_target_branch = "main"

# =============================================================================
# End of Configuration
# =============================================================================
"""

    config_path = Path("release_tool.toml")
    if config_path.exists():
        console.print("[yellow]Configuration file already exists at release_tool.toml[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    config_path.write_text(example_config)
    console.print(f"[green]Created configuration file: {config_path}[/green]")
    console.print("\n[blue]Next steps:[/blue]")
    console.print("1. Edit release_tool.toml and set your repository")
    console.print("2. Set GITHUB_TOKEN environment variable")
    console.print("3. Run: release-tool sync")
    console.print("4. Run: release-tool generate <version> --repo-path /path/to/repo")


def _merge_config_with_template(user_data: dict, template_doc) -> dict:
    """Merge user config with template, preserving comments and structure.

    Args:
        user_data: User's config as plain dict (from tomli)
        template_doc: Template loaded with tomlkit (has comments)

    Returns:
        Merged tomlkit document with template comments and user values
    """
    import tomlkit

    def to_tomlkit_value(value):
        """Convert plain Python value to tomlkit type to preserve comments."""
        if isinstance(value, dict):
            result = tomlkit.table()
            for k, v in value.items():
                result[k] = to_tomlkit_value(v)
            return result
        elif isinstance(value, list):
            result = tomlkit.array()
            for item in value:
                result.append(to_tomlkit_value(item))
            return result
        else:
            # Scalars (str, int, bool, etc.) are fine as-is
            return value

    def values_equal(val1, val2):
        """Check if two values are equal for merge purposes."""
        # Convert both to comparable types
        if isinstance(val1, (list, dict)) and isinstance(val2, (list, dict)):
            # Use unwrap to get plain Python objects for comparison
            v1 = val1.unwrap() if hasattr(val1, 'unwrap') else val1
            v2 = val2.unwrap() if hasattr(val2, 'unwrap') else val2
            return v1 == v2
        else:
            # For scalars, convert to string for comparison
            return str(val1) == str(val2)

    def update_values_in_place(template_item, user_value):
        """Update template values in-place with user values."""
        if isinstance(template_item, dict) and isinstance(user_value, dict):
            # Update each key in template with user's value
            # Create list of keys first to avoid "dictionary changed during iteration"
            for key in list(template_item.keys()):
                if key in user_value:
                    template_val = template_item[key]
                    user_val = user_value[key]

                    # SKIP updating if values are identical - this preserves comments!
                    if values_equal(template_val, user_val):
                        continue

                    # Check if we need to recurse
                    if isinstance(template_val, dict) and isinstance(user_val, dict):
                        update_values_in_place(template_val, user_val)
                    # Special handling for AoT (Array of Tables) - preserve the type
                    elif isinstance(template_val, tomlkit.items.AoT) and isinstance(user_val, list):
                        # Clear existing items and repopulate with user data
                        template_val.clear()
                        for item in user_val:
                            template_val.append(to_tomlkit_value(item))
                    elif isinstance(template_val, list) and isinstance(user_val, list):
                        # For regular lists, preserve trivia and convert to tomlkit array
                        old_trivia = template_val.trivia if hasattr(template_val, 'trivia') else None
                        new_val = to_tomlkit_value(user_val)
                        if old_trivia and hasattr(new_val, 'trivia'):
                            new_val.trivia.indent = old_trivia.indent
                            new_val.trivia.comment_ws = old_trivia.comment_ws
                            new_val.trivia.comment = old_trivia.comment
                            new_val.trivia.trail = old_trivia.trail
                        template_item[key] = new_val
                    else:
                        # Primitive value - preserve trivia and convert to tomlkit type
                        old_trivia = template_val.trivia if hasattr(template_val, 'trivia') else None
                        new_val = to_tomlkit_value(user_val)
                        if old_trivia and hasattr(new_val, 'trivia'):
                            new_val.trivia.indent = old_trivia.indent
                            new_val.trivia.comment_ws = old_trivia.comment_ws
                            new_val.trivia.comment = old_trivia.comment
                            new_val.trivia.trail = old_trivia.trail
                        template_item[key] = new_val

            # Add any keys from user that template doesn't have
            for key in user_value:
                if key not in template_item:
                    template_item[key] = to_tomlkit_value(user_value[key])

    def needs_update(template_section, user_section):
        """Check if a section needs any updates."""
        if not isinstance(template_section, dict) or not isinstance(user_section, dict):
            return True

        # Check if all keys in user section exist in template and have same values
        for key in user_section:
            if key not in template_section:
                return True  # New key needs to be added
            if not values_equal(template_section[key], user_section[key]):
                return True  # Value differs
        return False  # All values match, no update needed

    # Modify template in-place to preserve comments
    # Create list of keys first to avoid "dictionary changed during iteration"
    for key in list(template_doc.keys()):
        if key in user_data:
            template_item = template_doc[key]

            # Update values in place
            update_values_in_place(template_item, user_data[key])

    # Add any top-level keys user has that template doesn't have
    for key in user_data:
        if key not in template_doc:
            template_doc[key] = to_tomlkit_value(user_data[key])

    return template_doc


@cli.command()
@click.option(
    '--dry-run',
    is_flag=True,
    help='Show what would be upgraded without making changes'
)
@click.option(
    '--target-version',
    help='Target version to upgrade to (default: latest)'
)
@click.option(
    '--restore-comments',
    is_flag=True,
    help='Restore comments and reformat templates (works on same version)'
)
@click.pass_context
def update_config(ctx, dry_run: bool, target_version: Optional[str], restore_comments: bool):
    """Update configuration file to the latest version.

    This command upgrades your release_tool.toml configuration file to the
    latest format version, applying any necessary migrations.
    """
    from .migrations import MigrationManager
    import tomli
    import tomlkit

    # Determine config file path
    config_path = ctx.parent.params.get('config') if ctx.parent else None
    if not config_path:
        # Look for default config files
        default_paths = [
            "release_tool.toml",
            ".release_tool.toml",
            "config/release_tool.toml"
        ]
        for path in default_paths:
            if Path(path).exists():
                config_path = path
                break

    if not config_path:
        console.print("[red]Error: No configuration file found[/red]")
        console.print("Please specify a config file with --config or create one using:")
        console.print("  release-tool init-config")
        sys.exit(1)

    config_path = Path(config_path)
    console.print(f"[blue]Checking configuration file: {config_path}[/blue]\n")

    # Load current config
    try:
        with open(config_path, 'rb') as f:
            data = tomli.load(f)
    except Exception as e:
        console.print(f"[red]Error reading config file: {e}[/red]")
        sys.exit(1)

    # If restoring comments, load template and merge
    if restore_comments:
        try:
            template_path = Path(__file__).parent / "config_template.toml"
            with open(template_path, 'r', encoding='utf-8') as f:
                template_doc = tomlkit.load(f)

            # Merge: use template structure/comments but user's values
            data = _merge_config_with_template(data, template_doc)
            console.print("[dim]✓ Loaded comments from template[/dim]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load template comments: {e}[/yellow]")
            # Continue without comments - not critical

    # Check version
    manager = MigrationManager()
    current_version = data.get('config_version', '1.0')
    target_ver = target_version or manager.CURRENT_VERSION

    console.print(f"Current version: [yellow]{current_version}[/yellow]")
    console.print(f"Target version:  [green]{target_ver}[/green]\n")

    # Check if upgrade is needed (unless restoring comments)
    if not manager.needs_upgrade(current_version) and not restore_comments:
        console.print("[green]✓ Configuration is already up to date![/green]")
        return

    # If restoring comments on same version, show different message
    if restore_comments and current_version == target_ver:
        console.print("[blue]Restoring comments and reformatting templates...[/blue]\n")
    else:
        # Show changes
        changes = manager.get_changes_description(current_version, target_ver)
        console.print("[blue]Changes:[/blue]")
        console.print(changes)
        console.print()

    if dry_run:
        console.print("[yellow]Dry-run mode: No changes made[/yellow]")
        return

    # Get auto flag from context
    auto = ctx.obj.get('auto', False)

    # Confirm upgrade
    if not auto:
        if not click.confirm(f"Upgrade config from v{current_version} to v{target_ver}?"):
            console.print("[yellow]Upgrade cancelled[/yellow]")
            return

    # Apply migrations
    try:
        console.print(f"[blue]Upgrading configuration...[/blue]")

        # If restoring comments on same version, force run current version migration
        if restore_comments and current_version == target_ver:
            # For v1.1, reapply the v1.0 -> v1.1 migration to reformat templates
            if current_version == "1.1":
                from .migrations.v1_0_to_v1_1 import migrate as v1_1_migrate
                upgraded_data = v1_1_migrate(data)
            else:
                # For other versions, just use the data as-is
                upgraded_data = data
        else:
            # Normal upgrade path
            upgraded_data = manager.upgrade_config(data, target_ver)

        # Save back to file
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(tomlkit.dumps(upgraded_data))

        console.print(f"[green]✓ Configuration upgraded to v{target_ver}![/green]")
        console.print(f"[green]✓ Saved to {config_path}[/green]")

    except Exception as e:
        console.print(f"[red]Error during upgrade: {e}[/red]")
        sys.exit(1)


def main():
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
