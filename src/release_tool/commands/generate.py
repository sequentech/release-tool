import sys
import click
from typing import Optional, List, Set
from collections import defaultdict
from rich.console import Console

from ..config import Config, PolicyAction
from ..db import Database
from ..github_utils import GitHubClient
from ..git_ops import GitOperations, get_release_commit_range, determine_release_branch_strategy
from ..models import SemanticVersion
from ..template_utils import render_template, TemplateError
from ..policies import (
    TicketExtractor,
    CommitConsolidator,
    ReleaseNoteGenerator,
    VersionGapChecker,
    PartialTicketMatch,
    PartialTicketReason
)

console = Console()


def _get_issues_repo(config: Config) -> str:
    """
    Get the issues repository from config.

    Returns the first ticket_repos entry if available, otherwise falls back to code_repo.
    """
    if config.repository.ticket_repos and len(config.repository.ticket_repos) > 0:
        return config.repository.ticket_repos[0]
    return config.repository.code_repo


@click.command(context_settings={'help_option_names': ['-h', '--help']})
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

            # For patch bumps, check if the base version exists first
            # If it doesn't exist, use the base version instead of bumping
            if new_patch and base_version.patch == 0:
                # Need to check if base version exists in Git
                # Load config early to access repo path
                cfg = ctx.obj['config']
                try:
                    git_ops_temp = GitOperations(cfg.get_code_repo_path())
                    existing_versions = git_ops_temp.get_version_tags()
                    base_exists = any(
                        v.major == base_version.major and
                        v.minor == base_version.minor and
                        v.patch == base_version.patch and
                        v.prerelease == base_version.prerelease
                        for v in existing_versions
                    )

                    if not base_exists:
                        # Base version doesn't exist, use it instead of bumping
                        target_version = base_version
                        console.print(f"[blue]Base version {base_version.to_string()} does not exist → Creating {target_version.to_string()}[/blue]")
                    else:
                        # Base version exists, bump to next patch
                        target_version = base_version.bump_patch()
                        console.print(f"[blue]Base version {base_version.to_string()} exists → Bumping to {target_version.to_string()}[/blue]")
                except Exception as e:
                    # If we can't check, default to bumping
                    console.print(f"[yellow]Warning: Could not check existing versions ({e}), bumping patch[/yellow]")
                    target_version = base_version.bump_patch()
                    console.print(f"[blue]Bumping patch version → {target_version.to_string()}[/blue]")
            # Apply the bump for other cases
            elif new_major:
                target_version = base_version.bump_major()
                console.print(f"[blue]Bumping major version → {target_version.to_string()}[/blue]")
            elif new_minor:
                target_version = base_version.bump_minor()
                console.print(f"[blue]Bumping minor version → {target_version.to_string()}[/blue]")
            elif new_patch:
                # Patch != 0, just bump it
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

            # Determine head_ref for commit range
            # If we are creating a new branch, the head is the source branch
            # If we are using an existing branch, the head is that branch
            if should_create_branch:
                head_ref = source_branch
            else:
                head_ref = release_branch
                
            # If the branch exists remotely but not locally, we might need to prefix with origin/
            # However, git_ops usually handles local branches. 
            # If we are in dry-run and the branch exists only on remote, we should use origin/branch
            if not should_create_branch and not git_ops.branch_exists(head_ref) and git_ops.branch_exists(head_ref, remote=True):
                head_ref = f"origin/{head_ref}"

            comparison_version, commits = get_release_commit_range(
                git_ops,
                target_version,
                from_ver,
                head_ref=head_ref
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
            resolved_ticket_keys: Set[str] = set()  # Track successfully resolved tickets

            # Get expected ticket repository IDs
            expected_repos = config.get_ticket_repos()
            expected_repo_ids = []
            for ticket_repo_name in expected_repos:
                repo = db.get_repository(ticket_repo_name)
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
                        # Found in correct repo - mark as resolved
                        resolved_ticket_keys.add(change.ticket_key)
                        if debug:
                            console.print(f"\n[dim]📋 Found ticket in DB: #{ticket.number} - {ticket.title}[/dim]")

                    change.ticket = ticket

            # Apply partial ticket policy (with resolved/unresolved tracking)
            _handle_partial_tickets(partial_matches, resolved_ticket_keys, config, debug)

            # Check for inter-release duplicate tickets
            consolidated_changes = _check_inter_release_duplicates(
                consolidated_changes,
                target_version,
                db,
                repo_id,
                config,
                debug
            )

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
                doc_formatted_output = None
            else:
                # Determine release_output_path and doc_output_path
                release_output_path = output
                doc_output_path = None

                # If no explicit output provided, use config templates
                if not release_output_path:
                    # Build default draft path from config template
                    template_context = {
                        'code_repo': repo_name.replace('/', '-'),  # Sanitized for filesystem
                        'issue_repo': _get_issues_repo(config),    # First ticket_repos or code_repo
                        'version': version,
                        'major': str(target_version.major),
                        'minor': str(target_version.minor),
                        'patch': str(target_version.patch)
                    }
                    try:
                        release_output_path = render_template(config.output.draft_output_path, template_context)
                    except TemplateError as e:
                        console.print(f"[red]Error rendering draft_output_path template: {e}[/red]")
                        sys.exit(1)

                # Compute doc_output_path if configured
                if config.output.doc_output_path and config.release_notes.doc_output_template:
                    template_context = {
                        'code_repo': repo_name.replace('/', '-'),
                        'issue_repo': _get_issues_repo(config),
                        'version': version,
                        'major': str(target_version.major),
                        'minor': str(target_version.minor),
                        'patch': str(target_version.patch)
                    }
                    try:
                        doc_output_path = render_template(config.output.doc_output_path, template_context)
                    except TemplateError as e:
                        console.print(f"[red]Error rendering doc_output_path template: {e}[/red]")
                        sys.exit(1)

                # Format markdown with media processing
                result = note_generator.format_markdown(
                    grouped_notes,
                    version,
                    release_output_path=release_output_path,
                    doc_output_path=doc_output_path
                )

                # Handle return value (tuple or single string)
                if isinstance(result, tuple):
                    formatted_output, doc_formatted_output = result
                else:
                    formatted_output = result
                    doc_formatted_output = None

            # Output handling
            if dry_run:
                console.print(f"\n[yellow]{'='*80}[/yellow]")
                console.print(f"[yellow]DRY RUN - Release notes for {version}:[/yellow]")
                console.print(f"[yellow]{'='*80}[/yellow]\n")
                console.print(formatted_output)
                console.print(f"\n[yellow]{'='*80}[/yellow]")
                console.print(f"[yellow]DRY RUN complete. No files were created.[/yellow]")
                if doc_formatted_output:
                    console.print(f"[yellow](Docusaurus output would also be generated but is not shown in dry-run)[/yellow]")
                console.print(f"[yellow]{'='*80}[/yellow]\n")
            else:
                # Write release notes file
                release_path_obj = Path(release_output_path)
                release_path_obj.parent.mkdir(parents=True, exist_ok=True)
                release_path_obj.write_text(formatted_output)
                console.print(f"[green]✓ Release notes written to:[/green]")
                console.print(f"[green]  {release_path_obj.absolute()}[/green]")

                # Write doc output file if configured
                if doc_formatted_output and doc_output_path:
                    doc_path_obj = Path(doc_output_path)
                    doc_path_obj.parent.mkdir(parents=True, exist_ok=True)
                    doc_path_obj.write_text(doc_formatted_output)
                    console.print(f"[green]✓ Docusaurus release notes written to:[/green]")
                    console.print(f"[green]  {doc_path_obj.absolute()}[/green]")

                console.print(f"[blue]→ Review and edit the files, then use 'release-tool publish {version} -f {release_output_path}' to upload to GitHub[/blue]")

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


def _extract_ticket_keys_from_release_notes(release_body: str) -> Set[str]:
    """
    Extract ticket keys from release notes body.

    Args:
        release_body: The markdown body of release notes

    Returns:
        Set of ticket keys found in the release notes
    """
    import re
    ticket_keys = set()

    # Pattern 1: #1234 format
    for match in re.finditer(r'#(\d+)', release_body):
        ticket_keys.add(match.group(1))

    # Pattern 2: owner/repo#1234 format
    for match in re.finditer(r'[\w-]+/[\w-]+#(\d+)', release_body):
        ticket_keys.add(match.group(1))

    return ticket_keys


def _check_inter_release_duplicates(
    consolidated_changes: List,
    target_version: SemanticVersion,
    db: Database,
    repo_id: int,
    config,
    debug: bool
) -> List:
    """
    Check for tickets that appear in earlier releases and apply deduplication policy.

    Args:
        consolidated_changes: List of consolidated changes with tickets
        target_version: The version being generated
        db: Database instance
        repo_id: Repository ID
        config: Config with inter_release_duplicate_action policy
        debug: Debug mode flag

    Returns:
        Filtered list of consolidated changes (with duplicates removed if policy is IGNORE)
    """
    from ..models import SemanticVersion

    action = config.ticket_policy.inter_release_duplicate_action

    if action == PolicyAction.IGNORE and not debug:
        # Skip the check entirely if ignoring and not debugging
        pass

    # Get all earlier releases (semantically before target version)
    all_releases = db.get_all_releases(repo_id=repo_id, limit=None)

    earlier_releases = []
    for release in all_releases:
        try:
            release_version = SemanticVersion.parse(release.version)
            if release_version < target_version:
                earlier_releases.append(release)
        except ValueError:
            # Skip releases with invalid version strings
            continue

    if not earlier_releases:
        # No earlier releases to check against
        return consolidated_changes

    # Extract ticket keys from all earlier releases
    tickets_in_earlier_releases = {}  # ticket_key -> list of (version, release)
    for release in earlier_releases:
        if release.body:
            ticket_keys = _extract_ticket_keys_from_release_notes(release.body)
            for ticket_key in ticket_keys:
                if ticket_key not in tickets_in_earlier_releases:
                    tickets_in_earlier_releases[ticket_key] = []
                tickets_in_earlier_releases[ticket_key].append((release.version, release))

    # Check current changes against earlier releases
    duplicate_tickets = {}  # ticket_key -> list of versions
    for change in consolidated_changes:
        if change.ticket_key and change.ticket_key in tickets_in_earlier_releases:
            versions = [v for v, r in tickets_in_earlier_releases[change.ticket_key]]
            duplicate_tickets[change.ticket_key] = versions

    if not duplicate_tickets:
        # No duplicates found
        return consolidated_changes

    # Apply policy
    if action == PolicyAction.IGNORE:
        # Filter out duplicate tickets from consolidated_changes
        filtered_changes = [
            change for change in consolidated_changes
            if not (change.ticket_key and change.ticket_key in duplicate_tickets)
        ]

        if debug:
            console.print(f"\n[dim]Filtered out {len(duplicate_tickets)} duplicate ticket(s) found in earlier releases:[/dim]")
            for ticket_key, versions in duplicate_tickets.items():
                console.print(f"  [dim]• #{ticket_key} (in releases: {', '.join(versions)})[/dim]")

        return filtered_changes

    elif action == PolicyAction.WARN:
        # Include duplicates but warn
        msg_lines = []
        msg_lines.append("")
        msg_lines.append(f"[yellow]⚠️  Warning: Found {len(duplicate_tickets)} ticket(s) that appear in earlier releases:[/yellow]")
        for ticket_key, versions in duplicate_tickets.items():
            msg_lines.append(f"  • [bold]#{ticket_key}[/bold] (in releases: {', '.join(versions)})")
        msg_lines.append("")
        msg_lines.append("[dim]These tickets will be included in this release but also exist in earlier releases.[/dim]")
        msg_lines.append("[dim]To exclude duplicates, set ticket_policy.inter_release_duplicate_action = 'ignore'[/dim]")
        msg_lines.append("")
        console.print("\n".join(msg_lines))

        return consolidated_changes

    elif action == PolicyAction.ERROR:
        # Fail with error
        msg_lines = []
        msg_lines.append(f"[red]Error: Found {len(duplicate_tickets)} ticket(s) that appear in earlier releases:[/red]")
        for ticket_key, versions in duplicate_tickets.items():
            msg_lines.append(f"  • [bold]#{ticket_key}[/bold] (in releases: {', '.join(versions)})")
        console.print("\n".join(msg_lines))
        raise RuntimeError(f"Inter-release duplicate tickets found ({len(duplicate_tickets)} total). Policy: error")

    return consolidated_changes


def _display_partial_section(partials: List[PartialTicketMatch], section_title: str) -> List[str]:
    """
    Helper function to display a section of partial tickets with details.

    Args:
        partials: List of PartialTicketMatch objects to display
        section_title: Title for this section

    Returns:
        List of formatted message lines
    """
    msg_lines = []

    if not partials:
        return msg_lines

    # Group by type
    not_found = [p for p in partials if p.match_type == "not_found"]
    different_repo = [p for p in partials if p.match_type == "different_repo"]

    msg_lines.append(f"[cyan]{section_title}:[/cyan]")
    msg_lines.append("")

    # Handle different_repo partials
    if different_repo:
        msg_lines.append(f"[yellow]Tickets in different repository ({len(different_repo)}):[/yellow]")

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
        msg_lines.append(f"[yellow]Tickets not found in database ({len(not_found)}):[/yellow]")

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

    return msg_lines


def _handle_partial_tickets(
    all_partials: List[PartialTicketMatch],
    resolved_ticket_keys: Set[str],
    config,
    debug: bool
):
    """
    Handle partial ticket matches based on policy configuration.

    Args:
        all_partials: List of ALL PartialTicketMatch objects (resolved and unresolved)
        resolved_ticket_keys: Set of ticket keys that were eventually resolved
        config: Config object with ticket_policy.partial_ticket_action
        debug: Whether debug mode is enabled

    Raises:
        RuntimeError: If policy is ERROR and unresolved partials exist
    """
    if not all_partials:
        return

    action = config.ticket_policy.partial_ticket_action

    if action == PolicyAction.IGNORE:
        return

    # Split into resolved and unresolved
    unresolved_partials = [p for p in all_partials if p.ticket_key not in resolved_ticket_keys]
    resolved_partials = [p for p in all_partials if p.ticket_key in resolved_ticket_keys]

    # DEBUG MODE: Show both resolved and unresolved with full details
    if debug:
        msg_lines = []
        msg_lines.append("")

        # Header with counts
        if unresolved_partials and resolved_partials:
            msg_lines.append(f"[yellow]⚠️  Found {len(unresolved_partials)} unresolved and {len(resolved_partials)} resolved partial ticket match(es)[/yellow]")
        elif unresolved_partials:
            msg_lines.append(f"[yellow]⚠️  Found {len(unresolved_partials)} unresolved partial ticket match(es)[/yellow]")
        else:
            msg_lines.append(f"[green]✓ {len(resolved_partials)} partial ticket match(es) were fully resolved[/green]")
        msg_lines.append("")

        # Show unresolved section first (if any)
        if unresolved_partials:
            unresolved_section = _display_partial_section(unresolved_partials, "Unresolved Partial Matches")
            msg_lines.extend(unresolved_section)

        # Show resolved section (if any)
        if resolved_partials:
            resolved_section = _display_partial_section(resolved_partials, "Resolved Partial Matches")
            msg_lines.extend(resolved_section)

        # Add resolution tips for unresolved
        if unresolved_partials:
            msg_lines.append("[dim]To resolve:[/dim]")
            msg_lines.append("  1. Run [bold]'release-tool sync'[/bold] to fetch latest tickets")
            msg_lines.append("  2. Check [bold]repository.ticket_repos[/bold] in config")
            msg_lines.append("  3. Verify ticket numbers in branches/PRs")
            msg_lines.append("")

        console.print("\n".join(msg_lines))

    # WARN MODE: Brief message if all resolved, full details if any unresolved
    elif action == PolicyAction.WARN:
        if not unresolved_partials:
            # All resolved - brief message only
            console.print(f"[dim]ℹ️  {len(resolved_partials)} partial ticket match(es) were fully resolved. Use --debug for details.[/dim]")
        else:
            # Has unresolved - show full details for unresolved only
            msg_lines = []
            msg_lines.append("")
            msg_lines.append(f"[yellow]⚠️  Warning: Found {len(unresolved_partials)} unresolved partial ticket match(es)[/yellow]")
            if resolved_partials:
                msg_lines.append(f"[dim]({len(resolved_partials)} were resolved)[/dim]")
            msg_lines.append("")

            # Show unresolved details
            unresolved_section = _display_partial_section(unresolved_partials, "Unresolved Partial Matches")
            msg_lines.extend(unresolved_section)

            # Add resolution tips
            msg_lines.append("[dim]To resolve:[/dim]")
            msg_lines.append("  1. Run [bold]'release-tool sync'[/bold] to fetch latest tickets")
            msg_lines.append("  2. Check [bold]repository.ticket_repos[/bold] in config")
            msg_lines.append("  3. Verify ticket numbers in branches/PRs")
            msg_lines.append("")

            console.print("\n".join(msg_lines))

    # ERROR MODE: Fail if any unresolved
    if action == PolicyAction.ERROR and unresolved_partials:
        raise RuntimeError(f"Unresolved partial ticket matches found ({len(unresolved_partials)} total). Policy: error")
