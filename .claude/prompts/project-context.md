# Release Tool - Core Project Context

## What This Project Is

**release-tool** is a Python CLI application for managing semantic versioned releases. It automates the generation of release notes by:
1. Analyzing Git commit history between versions
2. Consolidating commits by parent tickets
3. Fetching ticket metadata from GitHub Issues
4. Categorizing changes by labels
5. Rendering formatted release notes via Jinja2 templates

## Technology Stack

- **Python 3.10+** with full type hints
- **PyGithub** - GitHub API v3 client
- **GitPython** - Local Git repository operations
- **Pydantic** - Data validation and settings
- **Click** - CLI framework
- **Rich** - Terminal formatting and progress bars
- **Jinja2** - Template engine
- **SQLite** - Local caching database
- **pytest** - Testing framework

## Architecture Overview

```
CLI (main.py)
    ↓
Database (db.py) ←→ GitHub API (github_utils.py)
    ↓                      ↓
Git Ops (git_ops.py)   Sync Manager (sync.py)
    ↓                      ↓
Policies (policies.py) ←→ Models (models.py)
    ↓
Output (Jinja2 templates)
```

## Core Data Models (models.py)

- `SemanticVersion` - Parse and compare versions (2.0.0, 1.5.0-rc.1)
- `Repository` - GitHub repository metadata
- `Ticket` - GitHub issue/ticket details
- `PullRequest` - GitHub PR with merge info
- `Commit` - Git commit with ticket association
- `Release` - GitHub release information
- `ReleaseNote` - Generated release note entry
- `Author` - Contributor information

## Key Workflows

### Sync Workflow (sync.py)
1. Get last sync timestamp from DB
2. Use GitHub Search API to find new tickets/PRs
3. Filter against existing items in database
4. Parallel fetch full details (20 workers)
5. Store incrementally with progress updates

### Generate Workflow (policies.py)
1. Extract commits between versions from Git
2. Extract ticket references from commits
3. Consolidate commits by parent ticket
4. Fetch ticket metadata from DB/GitHub
5. Categorize by labels
6. Render via Jinja2 template
7. Output to console/file/GitHub

## Performance Requirements (CRITICAL)

### Network Operations
- **ALWAYS use parallel processing** (ThreadPoolExecutor, 20 workers)
- **ALWAYS use GitHub Search API** instead of lazy iteration
- **NEVER** use `for item in repo.get_issues()` (slow, sequential)
- **ALWAYS** use `gh.search_issues(query)` (fast, paginated)

### Progress Feedback
- **NEVER** leave user waiting >2 seconds without output
- Show progress at every phase: searching, filtering, fetching
- Use Rich progress bars with percentage/count
- Example: "Searching for tickets..." → "Found 123 tickets" → "Fetching 45 new tickets in parallel..."

### Batch Sizes
- Search: Single API call per page (GitHub handles pagination)
- Fetch: 100-200 items per batch
- Workers: 20 parallel workers (safe for GitHub's 5000/hour limit)

## Code Patterns

### Good Pattern - Parallel Fetch
```python
console.print("[cyan]Searching for tickets...[/cyan]")
query = f"repo:{repo_name} is:issue"
issues = gh.search_issues(query)
console.print(f"[green]✓[/green] Found {len(issues)} tickets")

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(fetch_ticket, num): num for num in numbers}
    for future in as_completed(futures):
        ticket = future.result()
        progress.update(...)  # Show progress
```

### Bad Pattern - Sequential Iteration
```python
# DON'T DO THIS - Each iteration is a network call
for issue in repo.get_issues(state='all'):
    process(issue)
```

## Branch Management Strategy (CRITICAL)

### Automatic Release Branching
Release branches are **automatically created** based on semantic versioning rules:

#### Branching Rules:
1. **New Major (X.0.0)**: Branches from `main` (configurable via `branch_policy.default_branch`)
2. **New Minor (x.Y.0)**: Branches from previous release branch `release/{major}.{minor-1}` if it exists, otherwise from `main`
3. **Patch/RC (x.y.Z or x.y.z-rc.N)**: Uses existing release branch `release/{major}.{minor}`

#### Configuration (`release_tool.toml`):
```toml
[branch_policy]
release_branch_template = "release/{major}.{minor}"  # Branch naming pattern
default_branch = "main"                               # For new major versions
create_branches = true                                # Auto-create branches
branch_from_previous_release = true                   # Minor from previous release branch
```

#### Examples:
```bash
# 9.0.0 (new major) → Creates release/9.0 from main
release-tool generate 9.0.0 --dry-run

# 9.1.0 (new minor) → Creates release/9.1 from release/9.0
release-tool generate 9.1.0 --dry-run

# 9.1.0-rc (first RC) → Uses existing release/9.1, creates 9.1.0-rc.0
release-tool generate --new-rc --dry-run

# 9.0.5 (hotfix) → Uses existing release/9.0 (not release/9.1!)
release-tool generate 9.0.5 --dry-run
```

#### Important Notes:
- Branch creation happens during `generate` command (unless `create_branches = false`)
- Dry-run shows branch strategy without creating anything
- Tool displays: branch name, source branch, whether it will create
- Release branches persist for hotfix workflow
- See `docs/branching-strategy.md` for full documentation

## Release Generation Workflow (CRITICAL)

### Two-Step Process
Release generation is split into two distinct commands for safety and flexibility:

1. **`generate`** - Creates release notes (read-only, safe)
2. **`publish`** - Uploads to GitHub (writes to GitHub, needs confirmation)

### Generate Command
Creates release notes and saves to cache directory for review. Use `--dry-run` to preview without creating files.

#### Version Specification (pick ONE):
- **Explicit**: `release-tool generate 9.1.0`
- **Auto-bump major**: `release-tool generate --new-major` (1.2.3 → 2.0.0)
- **Auto-bump minor**: `release-tool generate --new-minor` (1.2.3 → 1.3.0)
- **Auto-bump patch**: `release-tool generate --new-patch` (1.2.3 → 1.2.4)
- **Create RC**: `release-tool generate --new-rc` (auto-increments: 1.2.3 → 1.2.3-rc.0, then 1.2.3-rc.1, etc.)

#### Key Options:
- `--dry-run` - Preview output without creating files or branches (ALWAYS use first!)
- `--output, -o` - Save to custom file path (defaults to `.release_tool_cache/draft-releases/{repo}/{version}.md`)
- `--format` - Output format: `markdown` (default) or `json`
- `--from-version` - Compare from specific version (auto-detected if omitted)
- `--repo-path` - Path to git repo (defaults to synced repo from `sync` command)

#### Default Output Behavior:
- **Without `--output`**: Saves to `.release_tool_cache/draft-releases/{repo}/{version}.md`
- **With `--dry-run`**: Only displays output to console, creates nothing
- **Path printed**: Full path is displayed so you can edit before publishing
- **Configurable**: Set `draft_output_path` in `release_tool.toml` to customize default path

#### Examples:
```bash
# ALWAYS start with dry-run to preview (uses synced repo automatically)
release-tool generate --new-minor --dry-run

# Generate and save to default cache path (recommended workflow)
release-tool generate --new-minor
# Output: ✓ Release notes written to: .release_tool_cache/draft-releases/owner-repo/9.1.0.md

# Create RC for testing (auto-increments: rc.0, rc.1, rc.2, etc.)
release-tool generate --new-rc
# Output: .release_tool_cache/draft-releases/owner-repo/9.1.0-rc.0.md

# Save to custom path if needed
release-tool generate --new-minor -o docs/releases/9.1.0.md

# Explicit version with dry-run
release-tool generate 9.1.0 --dry-run

# Use custom repo path if needed
release-tool generate --new-patch --repo-path /path/to/repo
```

### Publish Command
Uploads release notes to GitHub. Separated from generation for safety.

#### Key Options:
- `--notes-file, -f` - Path to markdown file with release notes (required for PR)
- `--release/--no-release` - Create GitHub release (default: true)
- `--pr/--no-pr` - Create PR with release notes (default: false)
- `--draft` - Create as draft release
- `--prerelease` - Mark as prerelease (auto-detected from version)

#### Examples:
```bash
# Publish release to GitHub
release-tool publish 9.1.0 -f docs/releases/9.1.0.md

# Create draft release for review
release-tool publish 9.1.0-rc.0 -f docs/releases/9.1.0-rc.0.md --draft

# Create PR without GitHub release
release-tool publish 9.1.0 -f docs/releases/9.1.0.md --pr --no-release

# Just create PR (for review process)
release-tool publish 9.1.0 -f docs/releases/9.1.0.md --pr --no-release
```

### Recommended Release Workflow
```bash
# 1. Sync repository first (one-time setup or to update)
release-tool sync

# 2. Generate with dry-run first (ALWAYS!)
release-tool generate --new-minor --dry-run

# 3. Generate and save to default cache location
release-tool generate --new-minor
# ✓ Release notes written to: .release_tool_cache/draft-releases/owner-repo/9.1.0.md

# 4. Review/edit the file if needed
vim .release_tool_cache/draft-releases/owner-repo/9.1.0.md

# 5. Publish to GitHub using the generated file
release-tool publish 9.1.0 -f .release_tool_cache/draft-releases/owner-repo/9.1.0.md

# For RC workflow (auto-increments RC numbers):
release-tool generate --new-rc  # Creates 9.1.0-rc.0
# Edit: .release_tool_cache/draft-releases/owner-repo/9.1.0-rc.0.md
release-tool publish 9.1.0-rc.0 -f .release_tool_cache/draft-releases/owner-repo/9.1.0-rc.0.md --draft

# Next RC (auto-increments to rc.1):
release-tool generate --new-rc  # Creates 9.1.0-rc.1
release-tool publish 9.1.0-rc.1 -f .release_tool_cache/draft-releases/owner-repo/9.1.0-rc.1.md --draft
```

## Testing Requirements (MANDATORY)

**CRITICAL**: All code changes MUST include unit tests and all tests MUST pass before committing.

### Rules
1. **Every new feature requires tests** - No exceptions
2. **All tests must pass** - Run `poetry run pytest tests/` before committing
3. **Test both success and error paths** - Happy path AND edge cases
4. **Mock external dependencies** - Don't hit real GitHub API in tests
5. **Use pytest fixtures** - Reuse setup code across tests

### Current Test Suite
- **Total tests**: 100 tests across 8 test files
- **Coverage requirement**: >80% for critical paths
- **Test execution**: All tests must complete in <1 second

### Test Patterns
- Use `pytest` fixtures for database, config, mocks
- Test file naming: `test_<module>.py`
- Test function naming: `test_<what_it_tests>`
- Assert specific values, not just truthiness

### Before Committing
```bash
# ALWAYS run this before committing
poetry run pytest tests/ -v

# All tests must pass - no exceptions
# If tests fail, fix them before committing
```

## Configuration (config.py)

Loaded from `release_tool.toml`:
- Repository settings (code_repo, ticket_repos)
- Sync configuration (parallel_workers, cutoff_date)
- Ticket policies (extraction patterns, consolidation)
- Version policies (tag_prefix, gap_detection)
- Branch policy (release_branch_template, default_branch, create_branches, branch_from_previous_release)
- Release note categories and templates
- Output settings (output_path, draft_output_path, assets_path, GitHub integration)

### Key Configuration Fields:
- **`output.draft_output_path`**: Default path for generated release notes (default: `.release_tool_cache/draft-releases/{repo}/{version}.md`)
- **`branch_policy.release_branch_template`**: Template for release branch names (default: `release/{major}.{minor}`)
- **`branch_policy.create_branches`**: Auto-create release branches (default: true)
- **`branch_policy.branch_from_previous_release`**: Branch new minors from previous release (default: true)

## Config Versioning System (CRITICAL)

**MANDATORY**: The configuration file (`release_tool.toml`) is versioned using semantic versioning. When making format changes, you MUST follow these rules strictly.

### Config Version Field
Every config file has a `config_version` field (e.g., `config_version = "1.1"`). This is automatically checked when loading the config.

### When to Increment Config Version

You MUST increment the config version when making ANY of these changes:

1. **Adding new required fields** to the config schema
2. **Removing fields** from the config schema
3. **Changing field types** or validation rules
4. **Modifying template variables** available in:
   - `entry_template`
   - `output_template`
   - `title_template`
   - `description_template`
   - PR templates (branch_template, title_template, body_template)
5. **Changing default template structure** (e.g., output_template formatting)
6. **Renaming fields** or changing field semantics

### When NOT to Increment

You do NOT need to increment version for:
- Bug fixes that don't affect config structure
- Internal code refactoring
- Documentation updates
- Adding optional fields with backward-compatible defaults

### Versioning Scheme

Use semantic versioning for config versions:
- **Major (2.0)**: Breaking changes that require manual intervention
- **Minor (1.1)**: Backward-compatible additions or improvements
- **Patch (1.1.1)**: Bug fixes (rare for config, usually use minor)

Current version: **1.1**

### Migration System

The migration system handles automatic upgrades of config files between versions.

#### Creating a Migration

When incrementing the config version, create a migration file in `src/release_tool/migrations/`:

```bash
# File naming: v{from}_to_v{to}.py (underscores for dots)
# Example: v1_0_to_v1_1.py for 1.0 → 1.1
```

Migration file structure:
```python
"""Migration from config version X.Y to X.Z.

Changes in X.Z:
- Change 1
- Change 2

This migration:
- What it does to the config
"""

from typing import Dict, Any

def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate config from version X.Y to X.Z."""
    updated_config = config_dict.copy()

    # Apply transformations
    # Example: Add new field with default
    if 'new_section' not in updated_config:
        updated_config['new_section'] = {'new_field': 'default_value'}

    # Example: Update template if still using old default
    if updated_config.get('template') == OLD_DEFAULT:
        updated_config['template'] = NEW_DEFAULT

    # Update version
    updated_config['config_version'] = 'X.Z'

    return updated_config
```

#### Migration Process

1. **Auto-detection**: When loading config, system checks `config_version`
2. **User prompt**: If old version detected, shows changes and prompts to upgrade
3. **Auto-upgrade**: With `--auto` flag, upgrades without prompting
4. **Migration chain**: Supports sequential upgrades (1.0 → 1.1 → 1.2)
5. **File update**: Upgraded config is saved back to the TOML file

#### Example Migration (v1.0 to v1.1)

```python
# src/release_tool/migrations/v1_0_to_v1_1.py

V1_0_DEFAULT_TEMPLATE = "..."  # Old default
V1_1_DEFAULT_TEMPLATE = "..."  # New default with improvements

def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from 1.0 to 1.1."""
    updated = config_dict.copy()

    # Only update template if user hasn't customized it
    if updated.get('output_template') == V1_0_DEFAULT_TEMPLATE:
        updated['output_template'] = V1_1_DEFAULT_TEMPLATE

    updated['config_version'] = '1.1'
    return updated
```

### Commands

#### Automatic Upgrade (on any command)
```bash
# If old config detected, prompts to upgrade
release-tool generate --new-minor

# Auto-upgrade without prompt
release-tool --auto generate --new-minor
```

#### Manual Upgrade Command
```bash
# Check current version and available upgrades
release-tool update-config

# Dry-run to preview changes
release-tool update-config --dry-run

# Auto-upgrade without prompt
release-tool --auto update-config

# Upgrade to specific version
release-tool update-config --target-version 1.1
```

### Version History

#### v1.1 (Current)
- Added `ticket_url` and `pr_url` template variables
- Made `url` a smart field (ticket_url if available, else pr_url)
- Improved `output_template` formatting with better spacing and blank lines
- Added `config_version` field for version tracking

#### v1.0 (Initial)
- Original config format
- Single `url` field in templates
- Basic output_template structure

## Documentation Maintenance (CRITICAL)

**MANDATORY**: When modifying CLI commands, features, or workflows, you MUST update documentation:

### What to Update:
1. **.claude/prompts/architecture.md** - Command list, module descriptions
2. **.claude/prompts/project-context.md** - Workflows, examples, configuration
3. **docs/*.md** - User-facing documentation (usage.md, configuration.md, etc.)
4. **Docstrings in code** - CLI help text, function descriptions

### When to Update:
- Adding/removing CLI commands or options
- Changing command behavior or defaults
- Adding new configuration options
- Modifying workflows or best practices
- Fixing bugs that affect user behavior

### Documentation Quality:
- Keep examples up-to-date with actual command names
- Include proper formatting (newlines after "Examples:")
- Test help text formatting: `release-tool <command> --help`
- Ensure consistency across all documentation files

## Common Issues to Avoid

1. **Slow sync** - Not using Search API or not parallelizing
2. **No feedback** - Missing console.print statements
3. **Type errors** - Missing type hints or Pydantic validation
4. **Test failures** - Not updating tests after refactoring
5. **Rate limiting** - Too many sequential requests (parallelize!)
6. **Outdated docs** - Not updating documentation when changing commands
