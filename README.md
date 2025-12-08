<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# release-tool

A comprehensive tool to manage releases using semantic versioning for efficient release workflows. Written in Python with full type safety and designed to be flexible and configurable for different team workflows.

## Features

- **Semantic Versioning Support**: Full support for semantic versioning with release candidates, betas, and alphas
- **Intelligent Version Comparison**: Automatically determines the right version to compare against (RC to RC, final to final, etc.)
- **Issue-based Consolidation**: Groups commits by parent issues for cleaner release notes
- **Configurable Policies**: Flexible policies for issue extraction, consolidation, version gaps, and more
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

## GitHub Actions Setup

When running `release-tool` in GitHub Actions, you need to configure proper authentication for accessing repositories, issues, and pull requests.

### Required Permissions

The GitHub token (`GITHUB_TOKEN`) needs the following permissions:

- **contents: read** - For cloning repositories and reading commit history
- **issues: read** - For fetching issue data
- **pull-requests: read** - For fetching pull request data
- **contents: write** - (Optional) For creating releases and pushing changes
- **pull-requests: write** - (Optional) For creating PRs with release notes

### Authentication Methods

The tool supports multiple authentication methods for cloning repositories:

#### 1. HTTPS with Token (Recommended for GitHub Actions)

```yaml
# .github/workflows/release.yml
name: Generate Release Notes

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Version to release (e.g., 1.0.0)'
        required: true

permissions:
  contents: write        # For cloning and creating releases
  issues: read          # For fetching issues
  pull-requests: read   # For fetching PRs

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install release-tool
        run: pip install release-tool

      - name: Generate release notes
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          release-tool sync
          release-tool generate ${{ github.event.inputs.version }} --upload
```

#### 2. SSH Authentication (For Private Repos with SSH Keys)

If you need to use SSH (e.g., for private repos without token access), configure your `release_tool.toml`:

```toml
[sync]
clone_method = "ssh"  # Options: "https", "ssh", "auto" (default)
```

Then set up SSH keys in your workflow:

```yaml
- name: Setup SSH
  uses: webfactory/ssh-agent@v0.9.0
  with:
    ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}

- name: Run release-tool
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}  # Still needed for API calls
  run: |
    release-tool sync
    release-tool generate ${{ github.event.inputs.version }}
```

#### 3. Auto Mode (Default)

By default, the tool uses `clone_method = "auto"` which:
1. First tries HTTPS with token authentication
2. Falls back to SSH if HTTPS fails

This provides the most flexibility across different environments.

### Custom GitHub Enterprise

For GitHub Enterprise or custom Git servers:

```toml
[github]
api_url = "https://github.enterprise.com/api/v3"

[sync]
clone_url_template = "https://github.enterprise.com/{repo_full_name}.git"
```

### Troubleshooting

If you encounter clone errors:

1. **Empty token error** (`https://@github.com/...`):
   - Ensure `GITHUB_TOKEN` is set in your environment
   - Check workflow permissions are correctly configured

2. **Permission denied**:
   - Verify token has required permissions
   - For private repos, ensure token can access the repository

3. **SSH authentication failed**:
   - Confirm SSH keys are properly configured
   - Test with: `ssh -T git@github.com`

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
issue_repo = "owner/issues"  # Optional: separate repo for issues
default_branch = "main"
```

### Sync Configuration
```toml
[sync]
clone_code_repo = true  # Whether to clone the repository locally
clone_method = "auto"   # Options: "https", "ssh", "auto" (default)
clone_url_template = ""  # Custom clone URL template (optional)
# Example: "https://github.enterprise.com/{repo_full_name}.git"
```

### Issue Policy
```toml
[issue_policy]
patterns = ["([A-Z]+-\\d+)", "#(\\d+)"]  # Regex patterns to find issues
no_issue_action = "warn"  # ignore, warn, or error
unclosed_issue_action = "warn"
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

### Issue Consolidation

Commits are consolidated by their parent issue:

1. Extract issue references from commits using configurable regex patterns
2. Try multiple strategies: commit message, PR body, branch name
3. Group commits with the same issue key
4. Fetch issue details from GitHub (title, labels, description)
5. Apply configurable policies for missing issues

### Release Note Generation

1. **Extract commits** between two versions from Git history
2. **Consolidate by issue** to group related changes
3. **Fetch issue metadata** from GitHub Issues API
4. **Categorize** based on labels and configured category mappings
5. **Format** using Jinja2 templates
6. **Output** to console, file, GitHub release, or PR

## Architecture

```
src/release_tool/
├── main.py          # CLI entry point with Click commands
├── models.py        # Pydantic data models (SemanticVersion, Commit, PR, Issue, etc.)
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
