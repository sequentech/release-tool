# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

import sys
import click
from typing import Optional, List, Set
from collections import defaultdict
from rich.console import Console

from ..config import Config, PolicyAction, DetectMode, OutputFormat, VersionBumpType, InclusionType, ReleaseVersionPolicy
from ..db import Database
from ..github_utils import GitHubClient
from ..git_ops import GitOperations, get_release_commit_range, determine_release_branch_strategy, find_comparison_version, find_comparison_version_for_docs
from ..models import SemanticVersion
from ..template_utils import render_template, TemplateError, build_repo_context
from ..policies import (
    IssueExtractor,
    CommitConsolidator,
    ReleaseNoteGenerator,
    VersionGapChecker,
    PartialIssueMatch,
    PartialIssueReason
)
from ..media_utils import MediaDownloader

console = Console()


def _get_issues_repo(config: Config) -> str:
    """
    Get the issues repository from config.

    Returns the first issue_repos entry if available, otherwise falls back to first code_repo.
    """
    if config.repository.issue_repos and len(config.repository.issue_repos) > 0:
        return config.repository.issue_repos[0].link
    return config.repository.code_repos[0].link


def _filter_changes_by_repos(consolidated_changes: List, target_repo_aliases: Optional[List[str]],
                              current_repo_alias: str, config: Config, db: Database) -> List:
    """
    Filter consolidated changes based on which repos they touched.

    Args:
        consolidated_changes: List of ConsolidatedChange objects
        target_repo_aliases: List of repo aliases to include changes from, or None for current repo only
        current_repo_alias: The current code repo alias being generated for
        config: Config object
        db: Database object

    Returns:
        Filtered list of changes
    """
    if target_repo_aliases is None:
        # Only include changes from current repo
        target_repo_aliases = [current_repo_alias]

    # Build map of repo link -> alias
    repo_link_to_alias = {repo.link: repo.alias for repo in config.repository.code_repos}

    # Get repo_ids for target aliases
    target_repo_ids = set()
    for alias in target_repo_aliases:
        repo_info = config.get_code_repo_by_alias(alias)
        if repo_info:
            # Get repo from database
            repo = db.get_repository(repo_info.link)
            if repo:
                target_repo_ids.add(repo.id)

    if not target_repo_ids:
        # No matching repos found, return all changes (fallback)
        return consolidated_changes

    # Filter changes: include if any commit or PR is from target repos
    filtered_changes = []
    for change in consolidated_changes:
        include_change = False

        # Check commits
        for commit in change.commits:
            if commit.repo_id in target_repo_ids:
                include_change = True
                break

        # Check PRs
        if not include_change:
            for pr in change.prs:
                if pr.repo_id in target_repo_ids:
                    include_change = True
                    break

        if include_change:
            filtered_changes.append(change)

    return filtered_changes


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('version', required=False)
@click.option('--from-version', help='Compare from this version (auto-detected if not specified)')
@click.option('--repo-path', type=click.Path(exists=True), help='Path to local git repository (defaults to pulled repo)')
@click.option('--output', '-o', type=click.Path(), help='Output file for release notes')
@click.option('--dry-run', is_flag=True, help='Show what would be generated without creating files')
@click.option('--new', type=click.Choice([e.value for e in VersionBumpType], case_sensitive=False), help='Auto-bump version')
@click.option('--detect-mode', type=click.Choice([e.value for e in DetectMode], case_sensitive=False), default=DetectMode.PUBLISHED.value, help='Detection mode for existing releases (default: published)')
@click.option('--format', type=click.Choice([e.value for e in OutputFormat], case_sensitive=False), default=OutputFormat.MARKDOWN.value, help='Output format (default: markdown)')
@click.pass_context
def generate(ctx, version: Optional[str], from_version: Optional[str], repo_path: Optional[str],
             output: Optional[str], dry_run: bool, new: Optional[str], detect_mode: str,
             format: str):
    """
    Generate release notes for a version.

    Analyzes commits between versions, consolidates by issue, and generates
    formatted release notes.

    VERSION can be specified explicitly (e.g., "9.1.0") or auto-calculated using
    --new option. Partial versions are supported (e.g., "9.2" + --new patch creates 9.2.1).

    Examples:

      release-tool generate 9.1.0

      release-tool generate --new minor

      release-tool generate --new rc

      release-tool generate 9.1.0 --dry-run

      release-tool generate --new patch --repo-path /custom/path

      release-tool generate 9.2 --new patch
    """
    # Get debug flag from global context
    debug = ctx.obj.get('debug', False)

    # Convert string parameters to Enums for type safety
    detect_mode_enum = DetectMode(detect_mode)
    format_enum = OutputFormat(format)

    if not version and not new:
        console.print("[red]Error: VERSION argument or --new option is required[/red]")
        return

    # Check if version is provided WITH a bump flag (partial version support)
    if version and new:
        # Parse as partial version to use as base
        try:
            base_version = SemanticVersion.parse(version, allow_partial=True)
            console.print(f"[blue]Using base version: {base_version.to_string()}[/blue]")

            # For patch bumps, check if the base version exists first
            # If it doesn't exist, use the base version instead of bumping
            if new == 'patch' and base_version.patch == 0:
                # Need to check if base version exists in Git
                # Load config early to access repo path
                cfg = ctx.obj['config']
                try:
                    # Use first code repo for version checking
                    first_repo_alias = cfg.repository.code_repos[0].alias
                    git_ops_temp = GitOperations(cfg.get_code_repo_path(first_repo_alias))
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
            elif new == 'major':
                target_version = base_version.bump_major()
                console.print(f"[blue]Bumping major version → {target_version.to_string()}[/blue]")
            elif new == 'minor':
                target_version = base_version.bump_minor()
                console.print(f"[blue]Bumping minor version → {target_version.to_string()}[/blue]")
            elif new == 'patch':
                # Patch != 0, just bump it
                target_version = base_version.bump_patch()
                console.print(f"[blue]Bumping patch version → {target_version.to_string()}[/blue]")
            elif new == 'rc':
                # Check if a final release exists for this base version
                # If yes, bump patch first, then create RC
                # Strategy: Check database FIRST, then optionally check git as fallback
                import re

                cfg = ctx.obj['config']
                final_exists = False
                rc_number = 0
                matching_rcs = []
                checked_db = False
                checked_git = False

                # Step 1: Check database for existing versions (primary source of truth)
                try:
                    db = Database(cfg.database.path)
                    db.connect()

                    # Use first code repo for version checking
                    repo_name = cfg.repository.code_repos[0].link
                    repo = db.get_repository(repo_name)

                    if repo:
                        # Debug: Show all releases in database
                        if debug:
                            all_db_releases = db.get_all_releases(repo_id=repo.id, limit=10)
                            console.print(f"[dim]Last 10 releases in database:[/dim]")
                            for rel in all_db_releases:
                                draft_str = " (draft)" if rel.is_draft else ""
                                console.print(f"[dim]  • {rel.version}{draft_str}[/dim]")
                        
                        # Check for final release of this base version
                        final_version_str = f"{base_version.major}.{base_version.minor}.{base_version.patch}"
                        all_releases = db.get_all_releases(
                            repo_id=repo.id,
                            version_prefix=final_version_str
                        )

                        if debug:
                            console.print(f"[dim]Looking for versions matching prefix: {final_version_str}[/dim]")
                            console.print(f"[dim]Found {len(all_releases)} matching releases[/dim]")
                            for rel in all_releases:
                                console.print(f"[dim]  • {rel.version} (draft={rel.is_draft})[/dim]")

                        for release in all_releases:
                            try:
                                v = SemanticVersion.parse(release.version)
                                
                                # For RC detection: check ALL releases (ignore detect_mode)
                                # We need to know what RC numbers exist to avoid duplicates
                                if (v.major == base_version.major and
                                    v.minor == base_version.minor and
                                    v.patch == base_version.patch and
                                    v.prerelease and v.prerelease.startswith('rc.')):
                                    matching_rcs.append(v)
                                    if debug:
                                        console.print(f"[dim]    Found RC: {v} (draft={release.is_draft})[/dim]")
                                
                                # For final version check: respect detect_mode
                                # Only consider published releases if detect_mode='published'
                                if detect_mode == 'published' and release.is_draft:
                                    continue
                                
                                # Check for exact final version match
                                if (v.major == base_version.major and
                                    v.minor == base_version.minor and
                                    v.patch == base_version.patch and
                                    v.is_final()):
                                    final_exists = True
                                    
                            except ValueError:
                                continue

                        checked_db = True

                    db.close()
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not check database for existing versions: {e}[/yellow]")

                # Step 2: Optionally check git tags (only if repo exists locally)
                # Only check git if detect_mode is 'all' or if we failed to check DB
                # If detect_mode is 'published', we should rely on DB because git tags don't have draft status
                if (detect_mode_enum == DetectMode.ALL or not checked_db):
                    try:
                        # Use first code repo for version checking
                        first_repo_alias = cfg.repository.code_repos[0].alias
                        repo_path = cfg.get_code_repo_path(first_repo_alias)
                        from pathlib import Path
                        if Path(repo_path).exists():
                            git_ops_temp = GitOperations(repo_path)
                            git_versions = git_ops_temp.get_version_tags()

                            if debug:
                                console.print(f"[dim]Found {len(git_versions)} version tags in git[/dim]")
                                # Show last 10
                                for v in sorted(git_versions, reverse=True)[:10]:
                                    console.print(f"[dim]  • {v.to_string()}[/dim]")

                            for v in git_versions:
                                # Check for final version
                                if (v.major == base_version.major and
                                    v.minor == base_version.minor and
                                    v.patch == base_version.patch and
                                    v.is_final()):
                                    final_exists = True
                                # Check for RCs
                                if (v.major == base_version.major and
                                    v.minor == base_version.minor and
                                    v.patch == base_version.patch and
                                    v.prerelease and v.prerelease.startswith('rc.')):
                                    if v not in matching_rcs:
                                        matching_rcs.append(v)

                            checked_git = True
                    except Exception as e:
                        # Git check is optional - not a critical failure
                        pass

                # Step 3: Determine target version based on what we found
                if final_exists:
                    # Final release exists - bump patch and create rc.0
                    source = "database" if checked_db else "git" if checked_git else "unknown"
                    console.print(f"[blue]Final release {base_version.to_string()} exists ({source}) → Bumping to next patch[/blue]")
                    base_version = base_version.bump_patch()
                    # Reset matching_rcs since we're now working with a new base version
                    matching_rcs = []
                    target_version = base_version.bump_rc(0)
                    console.print(f"[blue]Creating RC version → {target_version.to_string()}[/blue]")
                else:
                    # No final release - find existing RCs and auto-increment
                    if matching_rcs:
                        # Extract RC numbers and find the highest
                        rc_numbers = []
                        for v in matching_rcs:
                            match = re.match(r'rc\.(\d+)', v.prerelease)
                            if match:
                                rc_numbers.append(int(match.group(1)))

                        if rc_numbers:
                            rc_number = max(rc_numbers) + 1
                            source = "database" if checked_db else "git" if checked_git else "unknown"
                            console.print(f"[blue]Found existing RCs in {source}, incrementing to rc.{rc_number}[/blue]")
                    elif not checked_db and not checked_git:
                        console.print(f"[yellow]Warning: Could not check existing versions, creating rc.0[/yellow]")

                    target_version = base_version.bump_rc(rc_number)
                    console.print(f"[blue]Creating RC version → {target_version.to_string()}[/blue]")

            version = target_version.to_string()
            # Skip the auto-calculation below
            new = None
        except ValueError as e:
            console.print(f"[red]Error parsing version: {e}[/red]")
            return

    config: Config = ctx.obj['config']

    # Get list of repos to generate for (repos with pr_code configuration)
    pr_code_repo_aliases = config.get_pr_code_repos()

    if not pr_code_repo_aliases:
        console.print("[yellow]No pr_code configurations found. Please configure [output.pr_code.<alias>] sections in your config.[/yellow]")
        return

    # If repo_path is explicitly provided, use it for the first repo only (backward compat)
    if repo_path:
        console.print(f"[yellow]Warning: --repo-path is deprecated with multi-repo support. Using for first repo only.[/yellow]")
        explicit_repo_path = repo_path
    else:
        explicit_repo_path = None

    console.print(f"[bold cyan]Generating release notes for {len(pr_code_repo_aliases)} repository(ies)[/bold cyan]")

    # Initialize database once (shared across all repos)
    db = Database(config.database.path)
    db.connect()

    try:
        # Loop through each repo that has pr_code configuration
        for repo_alias in pr_code_repo_aliases:
            console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
            console.print(f"[bold magenta]Processing repository: {repo_alias}[/bold magenta]")
            console.print(f"[bold magenta]{'='*60}[/bold magenta]\n")

            repo_info = config.get_code_repo_by_alias(repo_alias)
            if not repo_info:
                console.print(f"[red]Error: Repository alias '{repo_alias}' not found in configuration[/red]")
                continue

            # Determine repo path (use pulled repo as default, or explicit if provided)
            if explicit_repo_path and repo_alias == pr_code_repo_aliases[0]:
                current_repo_path = explicit_repo_path
                console.print(f"[blue]Using explicitly provided path: {current_repo_path}[/blue]")
            else:
                current_repo_path = config.get_code_repo_path(repo_alias)
                console.print(f"[blue]Using pulled repository: {current_repo_path}[/blue]")

            # Verify repo path exists
            from pathlib import Path
            if not Path(current_repo_path).exists():
                console.print(f"[red]Error: Repository path does not exist: {current_repo_path}[/red]")
                console.print(f"[yellow]Tip: Run 'release-tool pull' first to clone the repository[/yellow]")
                continue  # Skip this repo, move to next

            # Get repository from database
            repo_name = repo_info.link
            repo = db.get_repository(repo_name)
            if not repo:
                console.print(f"[yellow]Repository {repo_name} not found in database. Running pull...[/yellow]")
                github_client = GitHubClient(config)
                repo = github_client.get_repository_info(repo_name)
                repo.id = db.upsert_repository(repo)
            repo_id = repo.id

            # Initialize Git operations
            git_ops = GitOperations(current_repo_path)

            # Auto-calculate version if using bump options
            if new:
                # Get all version tags from Git
                all_tags = git_ops.get_version_tags()
                all_tags.sort(reverse=True)
                
                latest_tag = None
                for tag in all_tags:
                    # Check if this tag is a draft in DB if detect_mode is published
                    if detect_mode_enum == DetectMode.PUBLISHED:
                        release = db.get_release(repo_id, tag.to_string())
                        if release and release.is_draft:
                            continue
                    
                    # For patch bumps, we only want final versions
                    if new == 'patch' and not tag.is_final():
                        continue
                        
                    latest_tag = tag
                    break

                if not latest_tag:
                    console.print("[red]Error: No suitable tags found in repository. Cannot auto-bump version.[/red]")
                    console.print("[yellow]Tip: Specify version explicitly or create an initial tag[/yellow]")
                    return

                base_version = latest_tag
                console.print(f"[blue]Latest version: {base_version.to_string()}[/blue]")

                if new == 'major':
                    target_version = base_version.bump_major()
                    console.print(f"[blue]Bumping major version → {target_version.to_string()}[/blue]")
                elif new == 'minor':
                    target_version = base_version.bump_minor()
                    console.print(f"[blue]Bumping minor version → {target_version.to_string()}[/blue]")
                elif new == 'patch':
                    target_version = base_version.bump_patch()
                    console.print(f"[blue]Bumping patch version → {target_version.to_string()}[/blue]")
                elif new == 'rc':
                    # Check if base_version is final - if so, bump patch first
                    import re
                    
                    if base_version.is_final():
                        # Base version is final - bump patch and create rc.0
                        console.print(f"[blue]Latest version {base_version.to_string()} is final → Bumping to next patch[/blue]")
                        base_version = base_version.bump_patch()
                        target_version = base_version.bump_rc(0)
                        console.print(f"[blue]Creating RC version → {target_version.to_string()}[/blue]")
                    else:
                        # Base version is not final - find the next RC number for this version
                        rc_number = 0

                        # Check existing versions for RCs of the same base version
                        matching_rcs = []
                        for v in all_tags:
                            if (v.major == base_version.major and
                                v.minor == base_version.minor and
                                v.patch == base_version.patch and
                                v.prerelease and v.prerelease.startswith('rc.')):
                                
                                if detect_mode_enum == DetectMode.PUBLISHED:
                                    release = db.get_release(repo_id, v.to_string())
                                    if release and release.is_draft:
                                        continue
                                matching_rcs.append(v)

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
            # Fetch remote refs first to ensure accurate branch detection
            git_ops.fetch_remote_refs()
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
                console.print(f"[blue]→ Using existing branch (analyzing commits from {release_branch})[/blue]")

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

            # Helper function to generate notes for a specific comparison policy
            def generate_notes_for_policy(policy: ReleaseVersionPolicy, explicit_from_ver: Optional[SemanticVersion] = None):
                """Generate release notes using the specified version comparison policy."""
                # Determine comparison version
                from_ver = explicit_from_ver

                if not from_ver:
                    # Calculate from_ver respecting detect_mode
                    available_versions = git_ops.get_version_tags()

                    if detect_mode_enum == DetectMode.PUBLISHED:
                        # Filter out drafts
                        filtered_versions = []
                        for v in available_versions:
                            release = db.get_release(repo_id, v.to_string())
                            if release and release.is_draft:
                                continue
                            filtered_versions.append(v)
                        available_versions = filtered_versions
                    elif detect_mode_enum == DetectMode.ALL:
                        # Add releases from DB that might be missing from local tags
                        try:
                            db_releases = db.get_all_releases(repo_id)
                            for release in db_releases:
                                try:
                                    v = SemanticVersion.parse(release.version)
                                    if v not in available_versions:
                                        available_versions.append(v)
                                except ValueError:
                                    continue
                            available_versions.sort()
                        except Exception as e:
                            console.print(f"[yellow]Warning: Could not fetch releases from DB: {e}[/yellow]")

                    # Use the provided policy to determine comparison version
                    from_ver = find_comparison_version_for_docs(
                        target_version,
                        available_versions,
                        policy=policy
                    )

                # Determine head_ref for commit range
                if should_create_branch:
                    head_ref = source_branch
                else:
                    head_ref = release_branch

                    # Ensure we can access the branch
                    if not git_ops.branch_exists(head_ref) and git_ops.branch_exists(head_ref, remote=True):
                        if not dry_run:
                            try:
                                git_ops.repo.git.fetch('origin', f"{head_ref}:{head_ref}")
                                console.print(f"[dim]Fetched {head_ref} from remote[/dim]")
                            except Exception as e:
                                console.print(f"[yellow]Could not fetch {head_ref}, using origin/{head_ref}: {e}[/yellow]")
                                head_ref = f"origin/{head_ref}"
                        else:
                            head_ref = f"origin/{head_ref}"

                # Get commits for this comparison
                comparison_version, commits = get_release_commit_range(
                    git_ops,
                    target_version,
                    from_ver,
                    head_ref=head_ref
                )

                if comparison_version:
                    console.print(f"[blue]Policy '{policy}': Comparing {comparison_version.to_string()} → {version}[/blue]")

                    # Check for version gaps
                    gap_checker = VersionGapChecker(config)
                    gap_checker.check_gap(comparison_version.to_string(), version)
                else:
                    console.print(f"[blue]Policy '{policy}': Generating notes for all commits up to {version}[/blue]")

                console.print(f"[blue]Found {len(commits)} commits for policy '{policy}'[/blue]")

                # Convert git commits to models
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

                # Extract issues and consolidate
                extractor = IssueExtractor(config, debug=debug)
                consolidator = CommitConsolidator(config, extractor, debug=debug)
                consolidated_changes = consolidator.consolidate(commit_models, pr_map)

                console.print(f"[blue]Consolidated into {len(consolidated_changes)} changes[/blue]")

                # Handle missing issues
                consolidator.handle_missing_issues(consolidated_changes)

                # Load issue information from database
                partial_matches: List[PartialIssueMatch] = []
                resolved_issue_keys: Set[str] = set()

                # Get expected issue repository IDs
                expected_repos = config.get_issue_repos()
                expected_repo_ids = []
                for issue_repo_name in expected_repos:
                    repo = db.get_repository(issue_repo_name)
                    if repo:
                        expected_repo_ids.append(repo.id)

                for change in consolidated_changes:
                    if change.issue_key:
                        issue = db.get_issue_by_key(change.issue_key)

                        if not issue:
                            extraction_source = _get_extraction_source(change)
                            partial = PartialIssueMatch(
                                issue_key=change.issue_key,
                                extracted_from=extraction_source,
                                match_type="not_found",
                                potential_reasons={
                                    PartialIssueReason.OLDER_THAN_CUTOFF,
                                    PartialIssueReason.TYPO,
                                    PartialIssueReason.PULL_NOT_RUN
                                }
                            )
                            partial_matches.append(partial)

                            if debug:
                                console.print(f"\n[yellow]⚠️  Issue {change.issue_key} not found in DB[/yellow]")

                        elif issue.repo_id not in expected_repo_ids:
                            found_repo = db.get_repository_by_id(issue.repo_id)
                            extraction_source = _get_extraction_source(change)
                            partial = PartialIssueMatch(
                                issue_key=change.issue_key,
                                extracted_from=extraction_source,
                                match_type="different_repo",
                                found_in_repo=found_repo.full_name if found_repo else "unknown",
                                issue_url=issue.url,
                                potential_reasons={
                                    PartialIssueReason.REPO_CONFIG_MISMATCH,
                                    PartialIssueReason.WRONG_ISSUE_REPOS
                                }
                            )
                            partial_matches.append(partial)

                            if debug:
                                console.print(f"\n[yellow]⚠️  Issue {change.issue_key} in different repo: {found_repo.full_name if found_repo else 'unknown'}[/yellow]")

                        else:
                            resolved_issue_keys.add(change.issue_key)
                            if debug:
                                console.print(f"\n[dim]📋 Found issue in DB: #{issue.number} - {issue.title}[/dim]")

                        change.issue = issue

                # Apply partial issue policy
                _handle_partial_issues(partial_matches, resolved_issue_keys, config, debug)

                # Check for inter-release duplicate issues
                consolidated_changes = _check_inter_release_duplicates(
                    consolidated_changes,
                    target_version,
                    db,
                    repo_id,
                    config,
                    debug
                )

                # Filter by inclusion policy
                consolidated_changes = _filter_by_inclusion_policy(
                    consolidated_changes,
                    config,
                    debug
                )

                # Filter by consolidated_code_repos_aliases (multi-repo filtering)
                # Get the consolidated repos from the first template (all templates in a policy group should have same value)
                template_list_for_policy = templates_by_policy.get(policy, [])
                if template_list_for_policy:
                    first_template = template_list_for_policy[0][1]  # (idx, template_config)
                    target_repo_aliases = first_template.consolidated_code_repos_aliases

                    if debug:
                        console.print(f"[dim]Filtering changes: target_repo_aliases={target_repo_aliases}, current_repo={repo_alias}[/dim]")

                    consolidated_changes = _filter_changes_by_repos(
                        consolidated_changes,
                        target_repo_aliases,
                        repo_alias,
                        config,
                        db
                    )

                    if debug:
                        console.print(f"[dim]After repo filtering: {len(consolidated_changes)} changes[/dim]")

                # Generate release notes
                note_generator = ReleaseNoteGenerator(config)
                release_notes = []
                for change in consolidated_changes:
                    note = note_generator.create_release_note(change, change.issue)
                    release_notes.append(note)

                # Group and format
                grouped_notes = note_generator.group_by_category(release_notes)

                return grouped_notes, comparison_version, commits

            # Parse explicit from_version if provided
            explicit_from_ver = SemanticVersion.parse(from_version) if from_version else None

            # Get pr_code config for this specific repo
            repo_pr_code = config.output.pr_code[repo_alias]

            # Group templates by their release_version_policy to optimize note generation
            # Templates with the same policy can share the same generated notes
            from collections import defaultdict
            templates_by_policy = defaultdict(list)

            if repo_pr_code.templates:
                for idx, template_config in enumerate(repo_pr_code.templates):
                    templates_by_policy[template_config.release_version_policy].append((idx, template_config))

            # Generate notes for each unique policy
            notes_by_policy = {}
            for policy, template_list in templates_by_policy.items():
                console.print(f"\n[bold cyan]Generating notes with policy: {policy}[/bold cyan]")
                grouped_notes, comparison_version, commits = generate_notes_for_policy(policy, explicit_from_ver)
                notes_by_policy[policy] = {
                    'grouped_notes': grouped_notes,
                    'comparison_version': comparison_version,
                    'commits': commits,
                    'templates': template_list
                }

            # Ensure INCLUDE_RCS notes are generated for draft file (GitHub releases)
            # if not already present from pr_code templates
            if repo_pr_code.templates and ReleaseVersionPolicy.INCLUDE_RCS not in notes_by_policy:
                console.print(f"\n[bold cyan]Generating notes with policy: {ReleaseVersionPolicy.INCLUDE_RCS} (for draft file)[/bold cyan]")
                grouped_notes, comparison_version, commits = generate_notes_for_policy(ReleaseVersionPolicy.INCLUDE_RCS, explicit_from_ver)
                notes_by_policy[ReleaseVersionPolicy.INCLUDE_RCS] = {
                    'grouped_notes': grouped_notes,
                    'comparison_version': comparison_version,
                    'commits': commits,
                    'templates': []
                }

            # For GitHub releases (no pr_code templates), use standard comparison
            if not repo_pr_code.templates:
                console.print(f"\n[bold cyan]Generating notes for GitHub release[/bold cyan]")
                # Use standard comparison for GitHub releases
                grouped_notes, comparison_version, commits = generate_notes_for_policy(ReleaseVersionPolicy.INCLUDE_RCS, explicit_from_ver)

            # Format output based on format option
            if format_enum == OutputFormat.JSON:
                import json
                # For JSON format, use the first policy's notes (or standard if no templates)
                if repo_pr_code.templates:
                    first_policy = list(notes_by_policy.keys())[0]
                    policy_data = notes_by_policy[first_policy]
                    grouped_notes = policy_data['grouped_notes']
                    comparison_version = policy_data['comparison_version']
                    commits = policy_data['commits']
                else:
                    # grouped_notes, comparison_version, commits already set above
                    pass

                # Convert to JSON
                json_output = {
                    'version': version,
                    'from_version': comparison_version.to_string() if comparison_version else None,
                    'num_commits': len(commits),
                    'categories': {}
                }
                for category, notes in grouped_notes.items():
                    json_output['categories'][category] = [
                        {
                            'title': note.title,
                            'issue_key': note.issue_key,
                            'description': note.description,
                            'labels': note.labels
                        }
                        for note in notes
                    ]
                formatted_output = json.dumps(json_output, indent=2)
                doc_formatted_output = None
            else:
                # Build template context for path rendering
                template_context = build_repo_context(config, current_repo_alias=repo_alias)
                template_context.update({
                    'version': version,
                    'major': str(target_version.major),
                    'minor': str(target_version.minor),
                    'patch': str(target_version.patch),
                })

                formatted_outputs = []

                # If explicit output provided, use the first policy's notes (or standard if no templates)
                if output:
                    if repo_pr_code.templates:
                        first_policy = list(notes_by_policy.keys())[0]
                        policy_data = notes_by_policy[first_policy]
                        grouped_notes = policy_data['grouped_notes']
                    else:
                        # grouped_notes already set from standard comparison above
                        pass

                    note_generator = ReleaseNoteGenerator(config)
                    result = note_generator.format_markdown(
                        grouped_notes,
                        version,
                        output_paths=[output]
                    )

                    if isinstance(result, list):
                        for item in result:
                            if isinstance(item, tuple):
                                content, path = item
                                formatted_outputs.append({'content': content, 'path': path})
                            else:
                                formatted_outputs.append({'content': item, 'path': output})
                    else:
                        formatted_outputs.append({'content': result, 'path': output})

                # Process each pr_code template with its own policy's notes
                elif repo_pr_code.templates:
                    note_generator = ReleaseNoteGenerator(config)

                    for idx, template_config in enumerate(repo_pr_code.templates):
                        template_policy = template_config.release_version_policy
                        path_context = template_context.copy()

                        # Adjust version in path for include-rcs mode
                        if not target_version.is_final() and template_policy == ReleaseVersionPolicy.INCLUDE_RCS:
                            path_context['version'] = version

                        # Set output_file_type for pr_code templates: code-0, code-1, etc.
                        path_context['output_file_type'] = f'code-{idx}'

                        # Get grouped_notes for this template's policy
                        policy_data = notes_by_policy[template_policy]
                        grouped_notes = policy_data['grouped_notes']

                        # Render output path using draft_output_path (not template_config.output_path)
                        # This ensures all drafts are in one predictable location
                        try:
                            output_path = render_template(config.output.draft_output_path, path_context)
                        except TemplateError as e:
                            console.print(f"[red]Error rendering draft_output_path for pr_code template #{idx}: {e}[/red]")
                            sys.exit(1)

                        # Initialize media downloader if enabled
                        media_downloader = None
                        if config.output.download_media and output_path:
                            media_downloader = MediaDownloader(
                                config.output.assets_path,
                                download_enabled=True
                            )

                        # Format using pr_code template directly
                        content = note_generator._format_with_pr_code_template(
                            template_config.output_template,
                            grouped_notes,
                            version,
                            output_path,
                            media_downloader
                        )

                        formatted_outputs.append({'content': content, 'path': output_path})

                    # ALWAYS write draft file in addition to pr_code templates
                    # Draft file uses DEFAULT_RELEASE_NOTES_TEMPLATE for GitHub releases
                    # Use INCLUDE_RCS policy for draft file (matching behavior when no pr_code templates)
                    try:
                        draft_context = template_context.copy()
                        draft_context['output_file_type'] = 'release'
                        draft_path = render_template(config.output.draft_output_path, draft_context)

                        # Use INCLUDE_RCS policy notes for draft (for GitHub releases)
                        policy_data = notes_by_policy[ReleaseVersionPolicy.INCLUDE_RCS]
                        draft_grouped_notes = policy_data['grouped_notes']

                        # Initialize media downloader if enabled
                        draft_media_downloader = None
                        if config.output.download_media and draft_path:
                            draft_media_downloader = MediaDownloader(
                                config.output.assets_path,
                                download_enabled=True
                            )

                        # Format using DEFAULT_RELEASE_NOTES_TEMPLATE directly (for GitHub releases)
                        draft_content = note_generator._format_with_master_template(
                            draft_grouped_notes,
                            version,
                            draft_path,
                            draft_media_downloader
                        )

                        formatted_outputs.append({'content': draft_content, 'path': draft_path})

                    except TemplateError as e:
                        console.print(f"[red]Error rendering draft_output_path: {e}[/red]")
                        sys.exit(1)

                # Backward compatibility: support old doc_output_path config
                elif config.release_notes.doc_output_template:
                    console.print("[yellow]Warning: doc_output_template is deprecated. Please migrate to pr_code.templates[/yellow]")
                    note_generator = ReleaseNoteGenerator(config)
                    result = note_generator.format_markdown(
                        grouped_notes,
                        version,
                        output_paths=[None]
                    )
                    if isinstance(result, list):
                        for item in result:
                            formatted_outputs.append({'content': item, 'path': None})
                    else:
                        formatted_outputs.append({'content': result, 'path': None})

                else:
                    # No templates configured, just format with standard notes
                    note_generator = ReleaseNoteGenerator(config)
                    result = note_generator.format_markdown(
                        grouped_notes,
                        version,
                        output_paths=[None]
                    )
                    if isinstance(result, list):
                        for item in result:
                            formatted_outputs.append({'content': item, 'path': None})
                    else:
                        formatted_outputs.append({'content': result, 'path': None})

                # Backward compatibility variables for old code
                formatted_output = formatted_outputs[0]['content'] if formatted_outputs else ""
                doc_formatted_output = formatted_outputs[1]['content'] if len(formatted_outputs) > 1 else None

            # Output handling
            if dry_run:
                console.print(f"\n[yellow]{'='*80}[/yellow]")
                console.print(f"[yellow]DRY RUN - Release notes for {version}:[/yellow]")
                console.print(f"[yellow]{'='*80}[/yellow]\n")
                console.print(formatted_output)
                console.print(f"\n[yellow]{'='*80}[/yellow]")
                if doc_formatted_output:
                    console.print(f"\n[bold]Documentation Release Notes Output:[/bold]")
                    console.print(f"[dim]{'─' * 60}[/dim]")
                    console.print(doc_formatted_output)
                    console.print(f"[dim]{'─' * 60}[/dim]")
                console.print(f"[yellow]{'='*80}[/yellow]\n")
                console.print(f"[yellow]DRY RUN complete. No files were created.[/yellow]")
            else:
                # Write all output files
                written_files = []
                for output_data in formatted_outputs:
                    if output_data['path'] and output_data['content']:
                        output_path_obj = Path(output_data['path'])
                        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
                        output_path_obj.write_text(output_data['content'])
                        written_files.append(output_path_obj.absolute())
                        console.print(f"[green]✓ Release notes written to:[/green]")
                        console.print(f"[green]  {output_path_obj.absolute()}[/green]")

                if written_files:
                    first_file = written_files[0]
                    console.print(f"[blue]→ Review and edit the files, then use 'release-tool push {version} -f {first_file}' to upload to GitHub[/blue]")
                else:
                    console.print(f"[yellow]⚠ No output files were written. Configure pr_code.templates in your config.[/yellow]")

            # End of for loop over pr_code repos

    except Exception as e:
        console.print(f"[red]Error generating release notes: {e}[/red]")
        if debug:
            raise
        sys.exit(1)
    finally:
        db.close()


def _get_extraction_source(change, commits_map=None, prs_map=None):
    """
    Get human-readable description of where a issue was extracted from.

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


def _extract_issue_keys_from_release_notes(release_body: str) -> Set[str]:
    """
    Extract issue keys from release notes body.

    Args:
        release_body: The markdown body of release notes

    Returns:
        Set of issue keys found in the release notes
    """
    import re
    issue_keys = set()

    # Pattern 1: #1234 format
    for match in re.finditer(r'#(\d+)', release_body):
        issue_keys.add(match.group(1))

    # Pattern 2: owner/repo#1234 format
    for match in re.finditer(r'[\w-]+/[\w-]+#(\d+)', release_body):
        issue_keys.add(match.group(1))

    return issue_keys


def _check_inter_release_duplicates(
    consolidated_changes: List,
    target_version: SemanticVersion,
    db: Database,
    repo_id: int,
    config,
    debug: bool
) -> List:
    """
    Check for issues that appear in earlier releases and apply deduplication policy.

    Args:
        consolidated_changes: List of consolidated changes with issues
        target_version: The version being generated
        db: Database instance
        repo_id: Repository ID
        config: Config with inter_release_duplicate_action policy
        debug: Debug mode flag

    Returns:
        Filtered list of consolidated changes (with duplicates removed if policy is IGNORE)
    """
    from ..models import SemanticVersion

    action = config.issue_policy.inter_release_duplicate_action

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

    # Extract issue keys from all earlier releases
    issues_in_earlier_releases = {}  # issue_key -> list of (version, release)
    for release in earlier_releases:
        if release.body:
            issue_keys = _extract_issue_keys_from_release_notes(release.body)
            for issue_key in issue_keys:
                if issue_key not in issues_in_earlier_releases:
                    issues_in_earlier_releases[issue_key] = []
                issues_in_earlier_releases[issue_key].append((release.version, release))

    # Check current changes against earlier releases
    duplicate_issues = {}  # issue_key -> list of versions
    for change in consolidated_changes:
        if change.issue_key and change.issue_key in issues_in_earlier_releases:
            versions = [v for v, r in issues_in_earlier_releases[change.issue_key]]
            duplicate_issues[change.issue_key] = versions

    if not duplicate_issues:
        # No duplicates found
        return consolidated_changes

    # Apply policy
    if action == PolicyAction.IGNORE:
        # Filter out duplicate issues from consolidated_changes
        filtered_changes = [
            change for change in consolidated_changes
            if not (change.issue_key and change.issue_key in duplicate_issues)
        ]

        if debug:
            console.print(f"\n[dim]Filtered out {len(duplicate_issues)} duplicate issue(s) found in earlier releases:[/dim]")
            for issue_key, versions in duplicate_issues.items():
                console.print(f"  [dim]• #{issue_key} (in releases: {', '.join(versions)})[/dim]")

        return filtered_changes

    elif action == PolicyAction.WARN:
        # Include duplicates but warn
        msg_lines = []
        msg_lines.append("")
        msg_lines.append(f"[yellow]⚠️  Warning: Found {len(duplicate_issues)} issue(s) that appear in earlier releases:[/yellow]")
        for issue_key, versions in duplicate_issues.items():
            msg_lines.append(f"  • [bold]#{issue_key}[/bold] (in releases: {', '.join(versions)})")
        msg_lines.append("")
        msg_lines.append("[dim]These issues will be included in this release but also exist in earlier releases.[/dim]")
        msg_lines.append("[dim]To exclude duplicates, set issue_policy.inter_release_duplicate_action = 'ignore'[/dim]")
        msg_lines.append("")
        console.print("\n".join(msg_lines))

        return consolidated_changes

    elif action == PolicyAction.ERROR:
        # Fail with error
        msg_lines = []
        msg_lines.append(f"[red]Error: Found {len(duplicate_issues)} issue(s) that appear in earlier releases:[/red]")
        for issue_key, versions in duplicate_issues.items():
            msg_lines.append(f"  • [bold]#{issue_key}[/bold] (in releases: {', '.join(versions)})")
        console.print("\n".join(msg_lines))
        raise RuntimeError(f"Inter-release duplicate issues found ({len(duplicate_issues)} total). Policy: error")

    return consolidated_changes


def _filter_by_inclusion_policy(
    consolidated_changes: List,
    config,
    debug: bool
) -> List:
    """
    Filter consolidated changes based on release_notes_inclusion_policy.

    This policy controls which types of changes appear in release notes:
    - "issues": Include changes associated with a issue/issue
    - "pull-requests": Include changes from pull requests (even without a issue)
    - "commits": Include direct commits (no PR, no issue)

    Args:
        consolidated_changes: List of ConsolidatedChange objects
        config: Config with release_notes_inclusion_policy in issue_policy
        debug: Debug mode flag

    Returns:
        Filtered list based on policy

    Example:
        With default ["issues", "pull-requests"]:
        - Commits with issues → Included (type="issue")
        - PRs with issues → Included (type="issue")
        - PRs without issues → Included (type="pr")
        - Commits without PRs or issues → EXCLUDED (type="commit")
    """
    from rich.console import Console
    console = Console()

    policy = set(config.issue_policy.release_notes_inclusion_policy)

    filtered = []
    excluded_count = {"commit": 0, "pr": 0, "issue": 0}

    for change in consolidated_changes:
        include = False

        # Check if change type is in policy
        if change.type == "issue" and InclusionType.ISSUES in policy:
            include = True
        elif change.type == "pr" and InclusionType.PULL_REQUESTS in policy:
            include = True
        elif change.type == "commit" and InclusionType.COMMITS in policy:
            include = True

        if include:
            filtered.append(change)
        else:
            excluded_count[change.type] += 1

    if debug and any(excluded_count.values()):
        console.print(f"\n[dim]Filtered by release_notes_inclusion_policy:[/dim]")
        for change_type, count in excluded_count.items():
            if count > 0:
                type_label = {
                    "commit": "standalone commit(s)",
                    "pr": "pull request(s) without issues",
                    "issue": "issue-linked change(s)"
                }.get(change_type, change_type)
                console.print(f"  [dim]• Excluded {count} {type_label}[/dim]")
        console.print(f"  [dim]• Policy: {sorted(policy)}[/dim]")

    return filtered


def _display_partial_section(partials: List[PartialIssueMatch], section_title: str) -> List[str]:
    """
    Helper function to display a section of partial issues with details.

    Args:
        partials: List of PartialIssueMatch objects to display
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
        msg_lines.append(f"[yellow]Issues in different repository ({len(different_repo)}):[/yellow]")

        # Group issues by reason
        issues_by_reason = defaultdict(list)
        for p in different_repo:
            for reason in p.potential_reasons:
                issues_by_reason[reason].append(p)

        # Show reasons with associated issues
        msg_lines.append(f"  [dim]This might be because of:[/dim]")
        for reason, issues in issues_by_reason.items():
            issue_keys = [p.issue_key for p in issues]
            msg_lines.append(f"    • {reason.description}")
            msg_lines.append(f"      [dim]Issues:[/dim] {', '.join(issue_keys)}")

        msg_lines.append("")
        msg_lines.append("  [dim]Details:[/dim]")
        for p in different_repo:
            msg_lines.append(f"    • [bold]{p.issue_key}[/bold] (from {p.extracted_from})")
            if p.found_in_repo:
                msg_lines.append(f"      [dim]Found in:[/dim] {p.found_in_repo}")
            if p.issue_url:
                msg_lines.append(f"      [dim]URL:[/dim] {p.issue_url}")
        msg_lines.append("")

    # Handle not_found partials
    if not_found:
        msg_lines.append(f"[yellow]Issues not found in database ({len(not_found)}):[/yellow]")

        # Group issues by reason
        issues_by_reason = defaultdict(list)
        for p in not_found:
            for reason in p.potential_reasons:
                issues_by_reason[reason].append(p)

        # Show reasons with associated issues
        msg_lines.append(f"  [dim]This might be because of:[/dim]")
        for reason, issues in issues_by_reason.items():
            issue_keys = [p.issue_key for p in issues]
            msg_lines.append(f"    • {reason.description}")
            msg_lines.append(f"      [dim]Issues:[/dim] {', '.join(issue_keys)}")

        msg_lines.append("")
        msg_lines.append("  [dim]Details:[/dim]")
        for p in not_found:
            msg_lines.append(f"    • [bold]{p.issue_key}[/bold] (from {p.extracted_from})")
        msg_lines.append("")

    return msg_lines


def _handle_partial_issues(
    all_partials: List[PartialIssueMatch],
    resolved_issue_keys: Set[str],
    config,
    debug: bool
):
    """
    Handle partial issue matches based on policy configuration.

    Args:
        all_partials: List of ALL PartialIssueMatch objects (resolved and unresolved)
        resolved_issue_keys: Set of issue keys that were eventually resolved
        config: Config object with issue_policy.partial_issue_action
        debug: Whether debug mode is enabled

    Raises:
        RuntimeError: If policy is ERROR and unresolved partials exist
    """
    if not all_partials:
        return

    action = config.issue_policy.partial_issue_action

    if action == PolicyAction.IGNORE:
        return

    # Split into resolved and unresolved
    unresolved_partials = [p for p in all_partials if p.issue_key not in resolved_issue_keys]
    resolved_partials = [p for p in all_partials if p.issue_key in resolved_issue_keys]

    # DEBUG MODE: Show both resolved and unresolved with full details
    if debug:
        msg_lines = []
        msg_lines.append("")

        # Header with counts
        if unresolved_partials and resolved_partials:
            msg_lines.append(f"[yellow]⚠️  Found {len(unresolved_partials)} unresolved and {len(resolved_partials)} resolved partial issue match(es)[/yellow]")
        elif unresolved_partials:
            msg_lines.append(f"[yellow]⚠️  Found {len(unresolved_partials)} unresolved partial issue match(es)[/yellow]")
        else:
            msg_lines.append(f"[green]✓ {len(resolved_partials)} partial issue match(es) were fully resolved[/green]")
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
            msg_lines.append("  1. Run [bold]'release-tool pull'[/bold] to fetch latest issues")
            msg_lines.append("  2. Check [bold]repository.issue_repos[/bold] in config")
            msg_lines.append("  3. Verify issue numbers in branches/PRs")
            msg_lines.append("")

        console.print("\n".join(msg_lines))

    # WARN MODE: Brief message if all resolved, full details if any unresolved
    elif action == PolicyAction.WARN:
        if not unresolved_partials:
            # All resolved - brief message only
            console.print(f"[dim]ℹ️  {len(resolved_partials)} partial issue match(es) were fully resolved. Use --debug for details.[/dim]")
        else:
            # Has unresolved - show full details for unresolved only
            msg_lines = []
            msg_lines.append("")
            msg_lines.append(f"[yellow]⚠️  Warning: Found {len(unresolved_partials)} unresolved partial issue match(es)[/yellow]")
            if resolved_partials:
                msg_lines.append(f"[dim]({len(resolved_partials)} were resolved)[/dim]")
            msg_lines.append("")

            # Show unresolved details
            unresolved_section = _display_partial_section(unresolved_partials, "Unresolved Partial Matches")
            msg_lines.extend(unresolved_section)

            # Add resolution tips
            msg_lines.append("[dim]To resolve:[/dim]")
            msg_lines.append("  1. Run [bold]'release-tool pull'[/bold] to fetch latest issues")
            msg_lines.append("  2. Check [bold]repository.issue_repos[/bold] in config")
            msg_lines.append("  3. Verify issue numbers in branches/PRs")
            msg_lines.append("")

            console.print("\n".join(msg_lines))

    # ERROR MODE: Fail if any unresolved
    if action == PolicyAction.ERROR and unresolved_partials:
        raise RuntimeError(f"Unresolved partial issue matches found ({len(unresolved_partials)} total). Policy: error")
