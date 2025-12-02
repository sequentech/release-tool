# release-tool

A comprehensive tool to manage releases using semantic versioning for efficient release workflows. Written in Python with full type safety and designed to be flexible and configurable for different team workflows.

## Features

- **Semantic Versioning Support**: Full support for semantic versioning with release candidates, betas, and alphas
- **Intelligent Version Comparison**: Automatically determines the right version to compare against (RC to RC, final to final, etc.)
- **Ticket-based Consolidation**: Groups commits by parent tickets for cleaner release notes
- **Configurable Policies**: Flexible policies for ticket extraction, consolidation, version gaps, and more
- **GitHub Integration**: Syncs PRs, issues, and releases from GitHub; can create releases and PRs automatically
- **Local Git Analysis**: Analyzes commit history from local repositories
- **SQLite Database**: Efficient local caching of GitHub data to minimize API calls
- **Template-based Release Notes**: Jinja2 templates for customizable release note formatting
- **Category-based Grouping**: Organize release notes by configurable categories with label mapping

## Installation

```bash
# Install with poetry
poetry install

# Or for development
poetry install --with dev
```

## Quick Start

1. **Initialize configuration**:
   ```bash
   release-tool init-config
   ```

2. **Edit** `release_tool.toml` and set your repository:
   ```toml
   [repository]
   code_repo = "your-org/your-repo"
   ```

3. **Set GitHub token**:
   ```bash
   export GITHUB_TOKEN="your_github_token"
   ```

4. **Sync repository data**:
   ```bash
   release-tool sync
   ```

5. **Generate release notes**:
   ```bash
   release-tool generate 1.0.0 --repo-path /path/to/local/repo
   ```

## CLI Commands

### `sync`
Sync repository data from GitHub to the local database:
```bash
release-tool sync [repository] [--repo-path PATH]
```

### `generate`
Generate release notes for a version:
```bash
release-tool generate VERSION \
  --repo-path /path/to/repo \
  [--from-version VERSION] \
  [--output FILE] \
  [--upload] \
  [--create-pr]
```

Options:
- `--from-version`: Compare from this version (auto-detected if not specified)
- `--output, -o`: Output file for release notes
- `--upload`: Upload release to GitHub
- `--create-pr`: Create PR with release notes

### `list-releases`
List all releases in the database:
```bash
release-tool list-releases [repository]
```

### `init-config`
Create an example configuration file:
```bash
release-tool init-config
```

## Configuration

The tool is configured via a TOML file (`release_tool.toml`). Key sections:

### Repository Configuration
```toml
[repository]
code_repo = "owner/repo"  # Required
ticket_repo = "owner/tickets"  # Optional: separate repo for tickets
default_branch = "main"
```

### Ticket Policy
```toml
[ticket_policy]
patterns = ["([A-Z]+-\\d+)", "#(\\d+)"]  # Regex patterns to find tickets
no_ticket_action = "warn"  # ignore, warn, or error
unclosed_ticket_action = "warn"
consolidation_enabled = true
```

### Version Policy
```toml
[version_policy]
gap_detection = "warn"  # ignore, warn, or error
tag_prefix = "v"
```

### Release Notes Categories
```toml
[[release_notes.categories]]
name = "Features"
labels = ["feature", "enhancement"]
order = 1

[[release_notes.categories]]
name = "Bug Fixes"
labels = ["bug", "fix"]
order = 2
```

### Output Configuration
```toml
[release_notes]
excluded_labels = ["skip-changelog", "internal"]
title_template = "Release {{ version }}"
include_authors = true
include_pr_links = true

[output]
output_file = "docs/releases/{major}.{minor}.{patch}.md"
create_github_release = false
create_pr = false
pr_branch_template = "release-notes-{version}"
```

## How It Works

### Version Comparison Logic

The tool implements intelligent version comparison:

- **Final versions** (e.g., `2.0.0`) compare to the previous final version
- **Release candidates** (e.g., `2.0.0-rc.2`) compare to:
  - Previous RC of the same version (`2.0.0-rc.1`) if it exists, OR
  - Previous final version if no RCs exist
- **Consolidated final releases** incorporate all changes from RCs, betas, alphas of that version

### Ticket Consolidation

Commits are consolidated by their parent ticket:

1. Extract ticket references from commits using configurable regex patterns
2. Try multiple strategies: commit message, PR body, branch name
3. Group commits with the same ticket key
4. Fetch ticket details from GitHub (title, labels, description)
5. Apply configurable policies for missing tickets

### Release Note Generation

1. **Extract commits** between two versions from Git history
2. **Consolidate by ticket** to group related changes
3. **Fetch ticket metadata** from GitHub Issues API
4. **Categorize** based on labels and configured category mappings
5. **Format** using Jinja2 templates
6. **Output** to console, file, GitHub release, or PR

## Architecture

```
src/release_tool/
├── main.py          # CLI entry point with Click commands
├── models.py        # Pydantic data models (SemanticVersion, Commit, PR, Ticket, etc.)
├── config.py        # Configuration management with Pydantic validation
├── db.py            # SQLite database operations
├── git_ops.py       # Git operations using GitPython
├── github_utils.py  # GitHub API client using PyGithub
└── policies.py      # Policy implementations (extraction, consolidation, generation)
```

## Testing

All modules have comprehensive unit tests:

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=release_tool

# Run specific test file
poetry run pytest tests/test_models.py -v
```

Current test coverage: 44 tests covering models, database, Git operations, policies, and configuration.

## Development

Built with modern Python best practices:

- **Python 3.10+**: Modern Python with type hints
- **Poetry**: Dependency management and packaging
- **Pydantic**: Data validation and settings management
- **Click**: Command-line interface
- **Rich**: Beautiful terminal output
- **PyGithub**: GitHub API integration
- **GitPython**: Local Git repository operations
- **Jinja2**: Template rendering
- **pytest**: Comprehensive testing

## Example Workflow

```bash
# 1. Initial setup
release-tool init-config
export GITHUB_TOKEN="ghp_your_token"

# 2. Edit release_tool.toml with your repo settings

# 3. Sync GitHub data once or periodically
release-tool sync

# 4. Generate release notes for version 2.0.0
release-tool generate 2.0.0 \
  --repo-path ~/projects/myrepo \
  --output docs/releases/2.0.0.md

# 5. Or generate and upload to GitHub
release-tool generate 2.0.0 \
  --repo-path ~/projects/myrepo \
  --upload

# 6. Or generate and create PR
release-tool generate 2.0.0 \
  --repo-path ~/projects/myrepo \
  --create-pr
```

## License

Copyright (c) Sequent Tech Inc. All rights reserved.
