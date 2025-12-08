---
id: configuration
title: Configuration
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Configuration

The tool is configured using a `release_tool.toml` file in the root of your project.

## Setup in Repository

1.  Create a file named `release_tool.toml` in your repository root.
2.  Add the following configuration structure:

```toml
[release]
tag_prefix = "v"           # Prefix for git tags
main_branch = "main"       # Main branch name

[github]
owner = "sequentech"       # GitHub organization or user

[database]
path = "release_tool.db"   # Local database path

[policies]
# Regex patterns to find issues in PR titles/bodies
issue_patterns = ["([A-Z]+-\\d+)"] 

# Categories for grouping release notes
categories = [
    "Features",
    "Bug Fixes",
    "Documentation",
    "Maintenance"
]

# Policy for handling version gaps (ignore, warn, error)
version_gap_policy = "warn"

# Mapping labels to categories
[policies.label_map]
"enhancement" = "Features"
"feature" = "Features"
"bug" = "Bug Fixes"
"fix" = "Bug Fixes"
"docs" = "Documentation"
"chore" = "Maintenance"
```

## Environment Variables

Sensitive information like tokens should be set via environment variables:

- `GITHUB_TOKEN`: Your GitHub Personal Access Token.

## Options Reference

### `release`

- `tag_prefix`: String to prepend to version numbers for git tags (e.g., "v" for "v1.0.0").
- `main_branch`: The name of the default branch (e.g., "main", "master").

### `github`

- `owner`: The GitHub account that owns the repositories.
- `token`: (Optional) GitHub Personal Access Token. Recommended to use `GITHUB_TOKEN` environment variable instead.
- `api_url`: (Optional) GitHub API URL. Default is `https://api.github.com`. Use for GitHub Enterprise.

### `sync`

Configuration for syncing data from GitHub.

#### `clone_code_repo`
- **Type**: `bool`
- **Description**: Whether to clone the code repository locally for offline operation.
- **Default**: `true`

#### `code_repo_path`
- **Type**: `str` (optional)
- **Description**: Local path where to clone/sync the code repository. If not specified, defaults to `.release_tool_cache/{repo_name}`.

#### `clone_method`
- **Type**: `str`
- **Description**: Method for cloning repositories.
- **Values**:
  - `"https"`: Clone using HTTPS with GitHub token authentication (recommended for GitHub Actions)
  - `"ssh"`: Clone using SSH (requires SSH keys configured)
  - `"auto"`: Try HTTPS first, fallback to SSH if it fails (default)
- **Default**: `"auto"`
- **Example**:
  ```toml
  [sync]
  clone_method = "https"  # For GitHub Actions
  ```

#### `clone_url_template`
- **Type**: `str` (optional)
- **Description**: Custom clone URL template for GitHub Enterprise or custom Git servers. Use `{repo_full_name}` as placeholder.
- **Example**:
  ```toml
  [sync]
  clone_url_template = "https://github.enterprise.com/{repo_full_name}.git"
  ```

#### `cutoff_date`
- **Type**: `str` (optional)
- **Description**: Only fetch issues/PRs created after this date (ISO format: YYYY-MM-DD). Speeds up initial sync.
- **Example**: `"2024-01-01"`

#### `parallel_workers`
- **Type**: `int`
- **Description**: Number of parallel workers for GitHub API calls.
- **Default**: `20`

#### `show_progress`
- **Type**: `bool`
- **Description**: Show progress updates during sync.
- **Default**: `true`

### `policies`

This section controls the behavior of the release tool's logic.

#### `issue_patterns`
- **Type**: `List[str]`
- **Description**: A list of regular expressions used to identify issue IDs in Pull Request titles and bodies.
- **Example**: `["([A-Z]+-\\d+)"]` matches issues like `JIRA-123`.

#### `categories`
- **Type**: `List[CategoryConfig]`
- **Description**: A list of category configurations for grouping release notes. Each category has a name, labels, order, and alias.
- **Structure**:
  ```toml
  [[release_notes.categories]]
  name = "🚀 Features"       # Display name shown in release notes
  labels = ["feature", "enhancement"]  # Labels that match this category
  order = 1                 # Display order (lower numbers appear first)
  alias = "features"        # Short identifier for templates
  ```

##### Fallback Category

**IMPORTANT**: One category must have `alias = "other"` to serve as the fallback for issues/PRs that don't match any other category's labels.

- **Name**: You can name it anything (e.g., "Other", "Miscellaneous", "Other Changes")
- **Labels**: Should be empty `[]` to catch unmatched items
- **Order**: Should be high (e.g., `99`) to appear last
- **Alias**: **MUST be `"other"`** for the tool to recognize it as the fallback

Example:
```toml
[[release_notes.categories]]
name = "Other"              # Customizable name
labels = []                 # Empty to catch all unmatched
order = 99                  # Display last
alias = "other"             # REQUIRED - do not change
```

The tool automatically assigns any issue or PR without matching labels to the category with `alias="other"`.

#### `version_gap_policy`
- **Type**: `str`
- **Description**: Determines how the tool handles gaps between the previous version and the new version (e.g., skipping from 1.0.0 to 1.2.0).
- **Values**:
    - `"ignore"`: Do nothing.
    - `"warn"`: Print a warning message but proceed.
    - `"error"`: Stop execution with an error.
- **Default**: `"warn"`

#### `label_map`
- **Type**: `Dict[str, str]`
- **Description**: A key-value mapping where keys are GitHub labels and values are the corresponding categories defined in `categories`.
- **Example**: `"enhancement" = "Features"` means PRs with the `enhancement` label will be listed under the "Features" section.
