"""Main CLI for the release tool."""

import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.table import Table

from .config import load_config, Config
from .db import Database
from .github_utils import GitHubClient
from .git_ops import GitOperations, get_release_commit_range
from .models import SemanticVersion
from .policies import (
    TicketExtractor,
    CommitConsolidator,
    ReleaseNoteGenerator,
    VersionGapChecker
)

console = Console()


@click.group()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    help='Path to configuration file'
)
@click.pass_context
def cli(ctx, config: Optional[str]):
    """Release tool for managing semantic versioned releases."""
    ctx.ensure_object(dict)
    # Don't load config for init-config command
    if ctx.invoked_subcommand != 'init-config':
        try:
            ctx.obj['config'] = load_config(config)
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
@click.argument('version')
@click.option('--from-version', help='Compare from this version (auto-detected if not specified)')
@click.option('--repo-path', type=click.Path(exists=True), required=True, help='Path to local git repository')
@click.option('--output', '-o', type=click.Path(), help='Output file for release notes')
@click.option('--upload/--no-upload', default=False, help='Upload release to GitHub')
@click.option('--create-pr/--no-pr', default=False, help='Create PR with release notes')
@click.pass_context
def generate(ctx, version: str, from_version: Optional[str], repo_path: str,
             output: Optional[str], upload: bool, create_pr: bool):
    """
    Generate release notes for a version.

    Analyzes commits between versions, consolidates by ticket, and generates
    formatted release notes.
    """
    config: Config = ctx.obj['config']

    console.print(f"[blue]Generating release notes for version {version}[/blue]")

    try:
        # Parse target version
        target_version = SemanticVersion.parse(version)

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
            extractor = TicketExtractor(config)
            consolidator = CommitConsolidator(config, extractor)
            consolidated_changes = consolidator.consolidate(commit_models, pr_map)

            console.print(f"[blue]Consolidated into {len(consolidated_changes)} changes[/blue]")

            # Handle missing tickets
            consolidator.handle_missing_tickets(consolidated_changes)

            # Fetch ticket information from GitHub
            github_client = GitHubClient(config)
            ticket_repo = config.repository.ticket_repo or repo_name

            for change in consolidated_changes:
                if change.ticket_key and change.ticket_key.startswith('#'):
                    # Fetch from GitHub if not in DB
                    ticket = db.get_ticket(repo_id, change.ticket_key)
                    if not ticket:
                        ticket = github_client.fetch_issue_by_key(
                            ticket_repo,
                            change.ticket_key,
                            repo_id
                        )
                        if ticket:
                            db.upsert_ticket(ticket)
                    change.ticket = ticket

            # Generate release notes
            note_generator = ReleaseNoteGenerator(config)
            release_notes = []
            for change in consolidated_changes:
                note = note_generator.create_release_note(change, change.ticket)
                release_notes.append(note)

            # Group and format
            grouped_notes = note_generator.group_by_category(release_notes)

            # Determine output path (use config default if not specified)
            final_output_path = output
            if not final_output_path and (create_pr or config.output.create_pr):
                # Use config output_path for PR creation
                version_parts = {
                    'version': version,
                    'major': str(target_version.major),
                    'minor': str(target_version.minor),
                    'patch': str(target_version.patch)
                }
                final_output_path = config.output.output_path.format(**version_parts)

            # Format markdown with media processing if output path is available
            markdown = note_generator.format_markdown(
                grouped_notes,
                version,
                output_path=final_output_path
            )

            # Output
            if final_output_path:
                output_path_obj = Path(final_output_path)
                output_path_obj.parent.mkdir(parents=True, exist_ok=True)
                output_path_obj.write_text(markdown)
                console.print(f"[green]Release notes written to {final_output_path}[/green]")
            else:
                console.print("\n" + "="*80)
                console.print(markdown)
                console.print("="*80 + "\n")

            # Upload to GitHub if requested
            if upload or config.output.create_github_release:
                console.print("[blue]Creating GitHub release...[/blue]")
                release_name = f"Release {version}"
                github_client.create_release(
                    repo_name,
                    version,
                    release_name,
                    markdown,
                    prerelease=not target_version.is_final()
                )

            # Create PR if requested
            if create_pr or config.output.create_pr:
                if final_output_path:
                    # Format PR templates
                    version_parts = {
                        'version': version,
                        'major': str(target_version.major),
                        'minor': str(target_version.minor),
                        'patch': str(target_version.patch),
                        'num_changes': sum(len(notes) for notes in grouped_notes.values()),
                        'num_categories': sum(1 for notes in grouped_notes.values() if notes)
                    }

                    branch_name = config.output.pr_templates.branch_template.format(**version_parts)
                    pr_title = config.output.pr_templates.title_template.format(**version_parts)
                    pr_body = config.output.pr_templates.body_template.format(**version_parts)

                    console.print("[blue]Creating PR with release notes...[/blue]")
                    github_client.create_pr_for_release_notes(
                        repo_name,
                        pr_title,  # Use formatted title instead of version
                        final_output_path,
                        markdown,
                        branch_name,
                        config.output.pr_target_branch,
                        pr_body  # Pass body as additional parameter
                    )
                else:
                    console.print("[yellow]Warning: output.output_path not configured, skipping PR creation[/yellow]")

        finally:
            db.close()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if '--debug' in sys.argv:
            raise
        sys.exit(1)


@cli.command()
@click.argument('repository', required=False)
@click.pass_context
def list_releases(ctx, repository: Optional[str]):
    """List all releases in the database."""
    config: Config = ctx.obj['config']
    repo_name = repository or config.repository.code_repo

    db = Database(config.database.path)
    db.connect()

    try:
        repo = db.get_repository(repo_name)
        if not repo:
            console.print(f"[red]Repository {repo_name} not found. Run 'sync' first.[/red]")
            return

        releases = db.get_all_releases(repo.id)

        if not releases:
            console.print("[yellow]No releases found.[/yellow]")
            return

        table = Table(title=f"Releases for {repo_name}")
        table.add_column("Version", style="cyan")
        table.add_column("Tag", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Published", style="magenta")

        for release in releases:
            version = SemanticVersion.parse(release.version)
            rel_type = "RC" if not version.is_final() else "Final"
            published = release.published_at.strftime("%Y-%m-%d") if release.published_at else "Draft"

            table.add_row(
                release.version,
                release.tag_name,
                rel_type,
                published
            )

        console.print(table)

    finally:
        db.close()


@cli.command('init-config')
def init_config():
    """Create an example configuration file."""
    example_config = """# =============================================================================
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
[ticket_policy]
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

# ORDER 4: GitHub issue reference in commit message
# Matches: "#123" in commit messages
[[ticket_policy.patterns]]
order = 4
strategy = "commit_message"
pattern = "#(?P<ticket>\\\\d+)"
description = "GitHub issue reference (#123) in commit"

# ORDER 5: JIRA-style tickets in commit message
# Matches: "PROJECT-123", "TICKET-456" in commit messages
[[ticket_policy.patterns]]
order = 5
strategy = "commit_message"
pattern = "(?P<project>[A-Z]+)-(?P<ticket>\\\\d+)"
description = "JIRA-style tickets (PROJ-123) in commit"

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


def main():
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
