<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Branching Strategy

The release tool implements an automated branching strategy that creates and manages release branches according to semantic versioning best practices.

## Overview

Release branches follow the pattern `release/{major}.{minor}` (configurable) and are automatically created based on the version being released. This enables:

- **Parallel development**: Work on multiple release lines simultaneously
- **Hotfix workflows**: Patch older releases without affecting newer ones
- **Clear release history**: Each major.minor gets its own dedicated branch

## How It Works

### Branch Creation Rules

The tool determines the source branch based on the version being released:

#### New Major Version (e.g., 9.0.0)
- **Source**: `main` (or configured `default_branch`)
- **Reason**: Major versions represent significant changes and start fresh from the main development line
- **Example**: `release/9.0` branches from `main`

#### New Minor Version (e.g., 9.1.0)
- **Source**: Previous release branch (e.g., `release/9.0`)
- **Fallback**: `main` if no previous release branch exists
- **Reason**: Minor versions build upon the previous minor release
- **Example**: `release/9.1` branches from `release/9.0`
- **Config**: Controlled by `branch_from_previous_release` setting

#### Patch or RC (e.g., 9.1.1 or 9.1.0-rc.1)
- **Source**: Existing release branch (e.g., `release/9.1`)
- **Reason**: Patches and RCs are built on the same release branch
- **No new branch created** if the release branch already exists

## Configuration

Configure the branching behavior in `release_tool.toml`:

```toml
[branch_policy]
# Template for release branch names
# Use {major}, {minor}, {patch} as placeholders
release_branch_template = "release/{major}.{minor}"

# Default branch for new major versions
default_branch = "main"

# Automatically create release branches
create_branches = true

# Branch new minor versions from previous release
branch_from_previous_release = true
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `release_branch_template` | `"release/{major}.{minor}"` | Template for branch names. Supports `{major}`, `{minor}`, `{patch}` placeholders |
| `default_branch` | `"main"` | Branch to use for new major versions |
| `create_branches` | `true` | Automatically create branches if they don't exist |
| `branch_from_previous_release` | `true` | Branch new minors from previous release branch |

## Examples

### Example 1: First Major Release

```bash
# Current state: No release branches exist
# Creating first 9.0.0 release

$ release-tool generate 9.0.0 --repo-path .

# Output:
# Release branch: release/9.0
# → Branch does not exist, will create from: main
# ✓ Created branch 'release/9.0' from 'main'
```

### Example 2: New Minor Release

```bash
# Current state: release/9.0 exists
# Creating 9.1.0 release

$ release-tool generate 9.1.0 --repo-path .

# Output:
# Release branch: release/9.1
# → Branch does not exist, will create from: release/9.0
# ✓ Created branch 'release/9.1' from 'release/9.0'
```

### Example 3: RC on Existing Branch

```bash
# Current state: release/9.1 exists with 9.1.0-rc.0
# Creating 9.1.0-rc.1

$ release-tool generate 9.1.0-rc.1 --repo-path .

# Output:
# Release branch: release/9.1
# → Using existing branch (source: release/9.1)
# (No branch creation needed)
```

### Example 4: Hotfix Patch Release

```bash
# Current state: release/9.0 and release/9.1 both exist
# Creating hotfix 9.0.5 for older release

$ release-tool generate 9.0.5 --repo-path .

# Output:
# Release branch: release/9.0
# → Using existing branch (source: release/9.0)
# (Commits will be based on release/9.0, not latest release/9.1)
```

## Branch Workflow

### Recommended Git Workflow

1. **Generate Release**
   ```bash
   release-tool generate --new-minor --repo-path . -o notes.md
   ```
   - Tool creates release branch automatically
   - You remain on your current working branch

2. **Review Branch**
   ```bash
   git branch -a | grep release/
   ```
   - Verify the release branch was created

3. **Optional: Checkout and Test**
   ```bash
   git checkout release/9.1
   # Run tests, build, etc.
   ```

4. **Publish Release**
   ```bash
   release-tool publish 9.1.0 -f notes.md
   ```

## Custom Branch Templates

You can customize the branch naming pattern:

```toml
[branch_policy]
# Custom template examples:

# Example 1: Include patch version
release_branch_template = "release/{major}.{minor}.{patch}"
# Results in: release/9.1.0

# Example 2: Different prefix
release_branch_template = "rel-{major}.{minor}.x"
# Results in: rel-9.1.x

# Example 3: Version prefix
release_branch_template = "v{major}.{minor}"
# Results in: v9.1
```

## Disabling Automatic Branch Creation

If you prefer to manage branches manually:

```toml
[branch_policy]
create_branches = false
```

With this setting, the tool will:
- ✅ Still determine which branch should be used
- ✅ Display the expected branch name
- ❌ **Not** automatically create the branch
- ⚠️ You must create the branch manually before generating

## Branching from Main Instead of Previous Release

To always branch from `main` instead of the previous release:

```toml
[branch_policy]
branch_from_previous_release = false
```

This changes the behavior:
- New major (9.0.0): Still from `main` ✓
- New minor (9.1.0): From `main` instead of `release/9.0`
- Use case: When releases are independent and don't build on each other

## Troubleshooting

### Branch Already Exists

If you see "Branch already exists" warnings:
- This is **expected** for subsequent RCs or patches
- The tool will use the existing branch
- No action needed

### Branch Not Found

If generation fails with "branch not found":
- Enable `create_branches = true` in config
- Or manually create the branch: `git branch release/9.1 main`

### Wrong Source Branch

If a branch was created from the wrong source:
- Delete the branch: `git branch -D release/9.1`
- Verify configuration in `release_tool.toml`
- Re-run `generate` command

## Integration with Version Gaps

The branching strategy works with the version gap detection:

```bash
# Attempting to skip from 9.0 to 9.2
$ release-tool generate 9.2.0 --repo-path .

# Output:
# Warning: Version gap detected: 9.0.0 → 9.2.0 (missing 9.1.x)
# Release branch: release/9.2
# → Branch does not exist, will create from: release/9.0
```

The tool will:
- Warn about the gap (based on `gap_detection` setting)
- Still create `release/9.2` from `release/9.0`
- Allow you to proceed or abort

## Best Practices

1. **Keep release branches**: Don't delete old release branches - they're needed for hotfixes
2. **Tag at release time**: Tag the commit when you publish the release
3. **Merge strategy**: Consider cherry-picking hotfixes to newer releases
4. **Dry-run first**: Always use `--dry-run` to preview branch creation
5. **Version consistency**: Ensure branch naming matches your tag naming convention

## See Also

- [Usage Guide](usage.md) - Basic command usage
- [Configuration](configuration.md) - Full configuration reference
- [Policies](policies.md) - Version policies and gap detection
