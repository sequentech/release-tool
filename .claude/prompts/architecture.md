<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Release Tool - System Architecture

## Module Breakdown

### main.py (CLI Entry Point)
**Purpose**: Command-line interface using Click

**Commands**:
- `sync` - Synchronize GitHub data (tickets, PRs, releases) to local database
- `generate` - Generate release notes for a version (saves to cache by default)
- `publish` - Publish release notes to GitHub (create release/PR)
- `list-releases` - List releases from database with filtering options
- `init-config` - Create example configuration file
- `update-config` - Upgrade configuration file to latest version

**Key Functions**:
- `cli()` - Main CLI group with config loading
- `sync()` - Orchestrates SyncManager for data fetching
- `generate()` - Orchestrates release note generation with auto-version bumping
- `publish()` - Creates GitHub releases/PRs from generated markdown files
- `list_releases()` - Queries database with filters (version, type, date range)

### models.py (Data Models)
**Purpose**: Pydantic models for type-safe data handling

**Core Models**:
- `SemanticVersion` - Parse/compare versions with prerelease support
- `Repository` - GitHub repo metadata (owner, name, default_branch)
- `Author` - Contributor info (username, email, display_name, avatar)
- `Label` - GitHub label (name, color, description)
- `Ticket` - GitHub issue (number, title, body, labels, state)
- `PullRequest` - GitHub PR (number, title, merged_at, author, labels)
- `Commit` - Git commit (sha, message, author, timestamp)
- `Release` - GitHub release (version, tag, body, published_at)
- `ReleaseNote` - Generated note (title, description, category, authors, PRs)

**Key Methods**:
- `SemanticVersion.parse()` - Parse version strings
- `SemanticVersion.compare()` - Version comparison logic
- `SemanticVersion.is_final()` - Check if not a prerelease

### config.py (Configuration Management)
**Purpose**: Load and validate configuration from TOML files

**Config Sections**:
- `RepositoryConfig` - code_repo, ticket_repos, default_branch
- `GitHubConfig` - token, api_url
- `DatabaseConfig` - SQLite database path
- `SyncConfig` - parallel_workers (20), cutoff_date, clone_code_repo
- `TicketPolicyConfig` - extraction patterns, consolidation rules
- `VersionPolicyConfig` - tag_prefix, gap_detection
- `ReleaseNoteConfig` - categories, templates, excluded_labels
- `OutputConfig` - output paths, GitHub release/PR creation

**Key Methods**:
- `load_config()` - Load from file with defaults (auto-upgrades old versions)
- `Config.from_file()` - Load from TOML with version checking
- `Config.from_dict()` - Create from dictionary
- `get_ticket_repos()` - Get ticket repositories list
- `get_category_map()` - Label to category mapping

### migrations/ (Config Migration System)
**Purpose**: Handle automatic upgrades of configuration files between versions

**Structure**:
- `migrations/manager.py` - MigrationManager class
- `migrations/v1_0_to_v1_1.py` - Individual migration scripts (one per version transition)

**MigrationManager Methods**:
- `compare_versions()` - Semantic version comparison using packaging library
- `needs_upgrade()` - Check if config version is outdated
- `get_migration_path()` - Find migration chain (e.g., 1.0 → 1.1 → 1.2)
- `_discover_migrations()` - Auto-discover migration files in migrations/ directory
- `load_migration()` - Dynamically load migration module
- `apply_migration()` - Execute single migration
- `upgrade_config()` - Apply full migration chain
- `get_changes_description()` - Human-readable change summary

**Migration File Format**:
Each migration is a Python file with a `migrate()` function:
```python
def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from version X to version Y."""
    # Transform config_dict
    # Update config_version
    return updated_config
```

**Auto-Upgrade Flow**:
1. Config loads, checks `config_version` field
2. If outdated, shows changes to user
3. Prompts to upgrade (or auto-upgrades with `--auto`)
4. Applies migration chain
5. Saves upgraded config back to TOML file

### db.py (Database Operations)
**Purpose**: SQLite database for local caching

**Tables**:
- `repositories` - Repository metadata
- `tickets` - GitHub issues
- `pull_requests` - GitHub PRs
- `commits` - Git commits with ticket associations
- `releases` - GitHub releases
- `authors` - Contributor information
- `sync_metadata` - Last sync timestamps for incremental updates

**Key Methods**:
- `connect()` / `close()` - Database lifecycle
- `init_db()` - Create schema
- `upsert_*()` - Insert or update records
- `get_existing_ticket_numbers()` - Fast filtering for incremental sync
- `get_last_sync()` - Get last sync timestamp
- `update_sync_metadata()` - Record sync completion

### git_ops.py (Git Operations)
**Purpose**: Local Git repository analysis

**Key Functions**:
- `get_release_commit_range()` - Get commits between two versions
- `find_comparison_version()` - Auto-detect version to compare against
  - Finals compare to previous final
  - RCs compare to previous RC of same version or previous final
- `get_all_tags()` - List all version tags
- `parse_version_from_tag()` - Extract version from tag name

### github_utils.py (GitHub API Client)
**Purpose**: Parallelized GitHub API operations

**GitHubClient Methods**:
- `get_repository_info()` - Fetch repository metadata
- `search_ticket_numbers()` - Fast search for tickets using Search API
- `search_pr_numbers()` - Fast search for PRs using Search API
- `fetch_issue()` - Get full ticket details
- `get_pull_request()` - Get full PR details
- `fetch_releases()` - Get all releases (parallelized)
- `create_release()` - Create GitHub release
- `create_pr_for_release_notes()` - Create PR with release notes

**Performance**:
- Uses GitHub Search API (not lazy iteration)
- ThreadPoolExecutor with 20 workers
- Batch processing for efficiency
- Progress feedback at all stages

### sync.py (Sync Manager)
**Purpose**: Orchestrate parallelized GitHub data synchronization

**SyncManager Methods**:
- `sync_all()` - Sync all data (tickets, PRs, git repo)
- `_sync_tickets_for_repo()` - Incremental ticket sync for a repository
- `_sync_pull_requests_for_repo()` - Incremental PR sync
- `_fetch_tickets_streaming()` - Parallel ticket fetch with progress
- `_fetch_prs_streaming()` - Parallel PR fetch with progress
- `_sync_git_repository()` - Clone or update local git repo

**Workflow**:
1. Get last sync timestamp
2. Search for new items (GitHub Search API)
3. Filter against existing DB items
4. Parallel fetch full details
5. Store incrementally
6. Update sync metadata

### policies.py (Business Logic)
**Purpose**: Implement ticket extraction, consolidation, and categorization

**Classes**:

**TicketExtractor**:
- Extract ticket references from commits, PRs, branches
- Multiple strategies with priority ordering
- Regex patterns for JIRA, GitHub issues, custom formats

**CommitConsolidator**:
- Group commits by parent ticket
- Consolidate multiple commits into single release note
- Use ticket title and description instead of commit messages

**ReleaseNoteGenerator**:
- Create ReleaseNote objects from commits/tickets
- Categorize by labels (Features, Bug Fixes, Breaking Changes, etc.)
- Apply exclusion rules (skip-changelog, internal, etc.)
- Group and sort by category

**VersionGapChecker**:
- Detect gaps in version sequence
- Policy actions: ignore, warn, error

### media_utils.py (Media Handling)
**Purpose**: Download and process media from ticket descriptions

**Functions**:
- `download_media_from_description()` - Extract and download images/videos
- `replace_media_urls()` - Update URLs to local paths in markdown

## Data Flow

### Sync Flow
```
User runs: release-tool sync
    ↓
SyncManager.sync_all()
    ↓
For each ticket_repo:
    ├─ GitHubClient.search_ticket_numbers() [GitHub Search API]
    ├─ Database.get_existing_ticket_numbers() [Filter]
    ├─ GitHubClient.fetch_issue() × N [Parallel, 20 workers]
    └─ Database.upsert_ticket() [Store]
    ↓
For code_repo:
    ├─ GitHubClient.search_pr_numbers() [GitHub Search API]
    ├─ Database.get_existing_pr_numbers() [Filter]
    ├─ GitHubClient.get_pull_request() × N [Parallel, 20 workers]
    └─ Database.upsert_pull_request() [Store]
    ↓
GitHubClient.fetch_releases() [Parallel]
    ↓
git clone/pull [If enabled]
```

### Generate Flow
```
User runs: release-tool generate 2.0.0 --repo-path ~/repo
    ↓
GitOps.find_comparison_version() [Auto-detect from version]
    ↓
GitOps.get_release_commit_range() [Extract commits from Git]
    ↓
TicketExtractor.extract_all() [Find ticket references]
    ↓
CommitConsolidator.consolidate() [Group by ticket]
    ↓
Database.fetch_ticket() [Get ticket metadata]
    ↓
ReleaseNoteGenerator.generate() [Create categorized notes]
    ↓
Jinja2 template rendering [Format output]
    ↓
Output to console / file / GitHub release / PR
```

## Design Patterns

### 1. Repository Pattern
- `Database` class abstracts SQLite operations
- Models define data structure
- DB operations return model instances

### 2. Strategy Pattern
- Multiple ticket extraction strategies
- Policy-based actions (warn, error, ignore)
- Template-based output rendering

### 3. Builder Pattern
- `ReleaseNoteGenerator` builds notes incrementally
- `Config` built from TOML with defaults

### 4. Parallel Processing Pattern
- ThreadPoolExecutor for I/O-bound operations
- `as_completed()` for progress tracking
- Batch processing for efficiency

### 5. Incremental Sync Pattern
- Track last sync timestamp
- Only fetch new/updated items
- Filter against existing DB data
