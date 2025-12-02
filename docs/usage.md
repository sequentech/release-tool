---
sidebar_position: 2
---

# Usage Guide

This guide provides a step-by-step walkthrough of how to use the Release Tool in your daily workflow.

## Prerequisites

Ensure you have the tool installed and configured as described in the [Installation](installation.md) and [Configuration](configuration.md) guides.

## Step-by-Step Workflow

### 1. Sync Repository Data

Before generating release notes, you need to sync the latest data from GitHub to your local database.

```bash
release-tool sync
```

This command:
- Clones the repository (first time) or updates it (subsequent runs)
- Fetches the latest tickets, PRs, and releases from GitHub
- Stores data in `.release_tool_cache/release_tool.db`

### 2. Generate Release Notes

Generate release notes using the `generate` command. You can specify the version explicitly or use auto-bump options.

#### Explicit Version
```bash
release-tool generate 9.1.0 --dry-run
```

#### Auto-Bump Options
```bash
# Bump major version (1.2.3 → 2.0.0)
release-tool generate --new-major --dry-run

# Bump minor version (1.2.3 → 1.3.0)
release-tool generate --new-minor --dry-run

# Bump patch version (finds latest final release, e.g., 9.2.0 → 9.2.1)
release-tool generate --new-patch --dry-run

# Create release candidate (auto-increments: 1.2.3-rc.0, 1.2.3-rc.1, etc.)
release-tool generate --new-rc --dry-run
```

#### Partial Version Support
You can use partial versions with bump flags:
```bash
# Use 9.2 as base, bump patch → 9.2.1
release-tool generate 9.2 --new-patch
```

### 3. Review and Edit

By default, release notes are saved to `.release_tool_cache/draft-releases/{repo}/{version}.md`:

```bash
# Generate saves to cache automatically
release-tool generate --new-minor
# Output: ✓ Release notes written to: .release_tool_cache/draft-releases/owner-repo/9.1.0.md

# Edit the file
vim .release_tool_cache/draft-releases/owner-repo/9.1.0.md
```

### 4. Publish Release

Once satisfied with the notes, publish to GitHub. The tool will automatically find your draft notes if you don't specify a file:

```bash
# Auto-finds draft notes for the version
release-tool publish 9.1.0

# Or explicitly specify a notes file
release-tool publish 9.1.0 -f .release_tool_cache/draft-releases/owner-repo/9.1.0.md
```

This will:
- Auto-find draft release notes (or use specified file)
- Create a git tag `v9.1.0`
- Create a GitHub release with the release notes
- Optionally create a PR with release notes (use `--pr`)

#### Testing Before Publishing

Use `--dry-run` to preview what would be published without making any changes:

```bash
# Preview the publish operation
release-tool publish 9.1.0 -f notes.md --dry-run

# Preview with specific flags
release-tool publish 9.1.0 -f notes.md --dry-run --release --pr --draft
```

#### Debugging Issues

Use `--debug` to see detailed information:

```bash
# Show verbose debugging information
release-tool publish 9.1.0 -f notes.md --debug

# Combine with dry-run for safe debugging
release-tool publish 9.1.0 -f notes.md --debug --dry-run
```

Debug mode shows:
- Configuration values being used
- Version parsing details
- Template substitution results
- File paths and content lengths
- Docusaurus file preview (if configured)

#### Using Configuration Defaults

Configure default behavior in `release_tool.toml`:

```toml
[output]
create_github_release = true  # Auto-create releases
create_pr = true               # Auto-create PRs
draft_release = false          # Publish immediately (not draft)
prerelease = "auto"            # Auto-detect prerelease from version (or true/false)
```

Prerelease options:
- `"auto"`: Auto-detect from version (e.g., `1.0.0-rc.1` → prerelease, `1.0.0` → stable)
- `true`: Always mark as prerelease
- `false`: Always mark as stable

Then simply run:

```bash
# Uses config defaults (auto-finds notes file)
release-tool publish 9.1.0

# Explicitly specify notes file
release-tool publish 9.1.0 -f notes.md

# Override config with CLI flags
release-tool publish 9.1.0 -f notes.md --no-release --pr --draft

# Override prerelease setting
release-tool publish 9.1.0 --prerelease true  # Force prerelease
release-tool publish 9.1.0 --prerelease false # Force stable
release-tool publish 9.1.0 --prerelease auto  # Auto-detect
```

## Common Commands

| Command | Description |
|---------|-------------|
| `sync` | Syncs repository, tickets, PRs, and releases from GitHub |
| `generate <version>` | Generates release notes for the specified version |
| `generate --new-major/minor/patch/rc` | Auto-bumps version and generates notes |
| `generate --dry-run` | Preview generated notes without creating files |
| `list-releases` | Lists releases from the database with filters |
| `publish <version>` | Creates a GitHub release (auto-finds draft notes) |
| `publish <version> -f <file>` | Creates a GitHub release from a markdown file |
| `publish --list` or `publish -l` | List all available draft releases |
| `publish --dry-run` | Preview publish operation without making changes |
| `publish --debug` | Show detailed debugging information |
| `publish --prerelease auto\|true\|false` | Control prerelease status |
| `init-config` | Creates an example configuration file |

## Advanced Usage

### List Draft Releases

View all available draft releases that are ready to be published:

```bash
# List all draft releases
release-tool publish --list

# Or use the shorthand
release-tool publish -l
```

This shows a table with:
- Code Repository
- Version
- Type (RC or Final)
- Created timestamp
- File path

### Auto-Finding Draft Notes

When publishing without specifying `--notes-file`, the tool automatically searches for matching draft notes:

```bash
# Automatically finds .release_tool_cache/draft-releases/{repo}/9.1.0.md
release-tool publish 9.1.0
```

If no matching draft is found, it displays all available drafts and exits with an error.

### List Releases

View releases with various filters:

```bash
# Show last 10 releases (default)
release-tool list-releases

# Show all releases
release-tool list-releases --limit 0

# Filter by version prefix
release-tool list-releases --version "9.3"

# Filter by type
release-tool list-releases --type final
release-tool list-releases --type rc --type final

# Filter by date
release-tool list-releases --after 2024-01-01
release-tool list-releases --before 2024-06-01
```

### Branch Management

The tool automatically manages release branches:
- New major versions (9.0.0) branch from `main`
- New minor versions (9.1.0) branch from previous release branch (`release/9.0`)
- Patches and RCs use existing release branches

See [Branching Strategy](branching-strategy.md) for details.
