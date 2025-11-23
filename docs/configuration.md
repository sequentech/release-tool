---
sidebar_position: 3
---

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
# Regex patterns to find tickets in PR titles/bodies
ticket_patterns = ["([A-Z]+-\\d+)"] 

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

### `policies`

This section controls the behavior of the release tool's logic.

#### `ticket_patterns`
- **Type**: `List[str]`
- **Description**: A list of regular expressions used to identify ticket IDs in Pull Request titles and bodies.
- **Example**: `["([A-Z]+-\\d+)"]` matches tickets like `JIRA-123`.

#### `categories`
- **Type**: `List[str]`
- **Description**: An ordered list of category names. Release notes will be grouped into these categories in the order specified.
- **Default**: `["Features", "Bug Fixes", "Other"]`

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
