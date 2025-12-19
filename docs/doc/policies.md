---
id: policies
title: Policies
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Policies

The Release Tool uses various policies to control its behavior. These policies can be configured to match your workflow. See the [Configuration](configuration.md) guide for details on how to set them up in `.release_tool.toml`.

## Version Policy

Controls version comparison, gap detection, and release candidate handling.

### Gap Detection (`gap_detection`)

Detects missing versions in the release sequence (e.g., releasing 1.2.0 when 1.1.0 was never released).

**Options:** `ignore`, `warn`, `error`
**Default:** `warn`

**Example:**
```toml
[version_policy]
gap_detection = "warn"
```

**Use Cases:**
- `warn`: Notify about gaps but allow release (recommended)
- `error`: Enforce strict sequential versioning
- `ignore`: Allow any version jumps

### Tag Prefix (`tag_prefix`)

Defines the prefix used for version tags in Git.

**Default:** `"v"` (e.g., `v1.0.0`)

**Example:**
```toml
[version_policy]
tag_prefix = "v"
```

## Issue Policy

Controls how issues are extracted from commits and PRs, and how they're handled when missing or problematic.

### No Issue Action (`no_issue_action`)

What to do when a commit or PR has no associated issue.

**Options:** `ignore`, `warn`, `error`
**Default:** `warn`

**Example:**
```toml
[issue_policy]
no_issue_action = "warn"
```

**Use Cases:**
- `warn`: Allow untracked work but notify (recommended)
- `error`: Enforce strict issue tracking (all work must have an issue)
- `ignore`: Don't require issues (less formal workflow)

### Unclosed Issue Action (`unclosed_issue_action`)

What to do when an issue referenced in the release is still open.

**Options:** `ignore`, `warn`, `error`
**Default:** `warn`

**Example:**
```toml
[issue_policy]
unclosed_issue_action = "warn"
```

**Use Cases:**
- `warn`: Include open issues but notify (recommended)
- `error`: Only release closed issues
- `ignore`: Don't check issue status

### Partial Issue Action (`partial_issue_action`)

What to do when an issue is extracted but not found in the database or found in a different repository.

**Options:** `ignore`, `warn`, `error`
**Default:** `warn`

**Partial matches occur when:**
- Issue extracted from branch/PR but not in database (older than cutoff date, typo, sync not run)
- Issue found in wrong repository (config mismatch)

**Example:**
```toml
[issue_policy]
partial_issue_action = "warn"
```

**Use Cases:**
- `warn`: Show details about partial matches with potential causes (recommended)
- `error`: Fail if any issues can't be fully resolved
- `ignore`: Continue without checking

### Inter-Release Duplicate Action (`inter_release_duplicate_action`)

What to do when an issue appears in multiple releases (e.g., issue in both 9.2.0 and 9.3.0).

**Options:** `ignore`, `warn`, `error`
**Default:** `warn`

**Example:**
```toml
[issue_policy]
inter_release_duplicate_action = "warn"
```

**Use Cases:**
- `ignore`: Exclude duplicates from new release (one issue per release)
- `warn`: Include duplicates but notify (recommended)
- `error`: Fail if duplicates detected

### Consolidation Enabled (`consolidation_enabled`)

Whether to group multiple commits by their parent issue.

**Options:** `true`, `false`
**Default:** `true`

**Example:**
```toml
[issue_policy]
consolidation_enabled = true
```

**Behavior:**
- `true`: Multiple commits for the same issue → single release note entry
- `false`: Each commit → separate release note entry

### Release Notes Inclusion Policy (`release_notes_inclusion_policy`)

Controls which types of changes appear in release notes.

**Options:** List containing: `"issues"`, `"pull-requests"`, `"commits"`
**Default:** `["issues", "pull-requests"]`

**Change Types:**
- **`issues`**: Commits/PRs with associated issues
- **`pull-requests`**: PRs without associated issues
- **`commits`**: Direct commits (no PR, no issue)

**Example:**
```toml
[issue_policy]
release_notes_inclusion_policy = ["issues", "pull-requests"]
```

**Common Configurations:**
1. **`["issues", "pull-requests"]`** (default): Include issue-tracked work and PRs, exclude standalone commits
2. **`["issues"]`**: Only show work with issues (strict tracking)
3. **`["issues", "pull-requests", "commits"]`**: Show everything
4. **`["pull-requests"]`**: Only show untracked PRs (unusual)

## Branch Policy

Controls how release branches are created and managed.

### Release Branch Template (`release_branch_template`)

Jinja2 template for release branch names.

**Default:** `"release/{{major}}.{{minor}}"`

**Example:**
```toml
[branch_policy]
release_branch_template = "release/{{major}}.{{minor}}"
```

### Default Branch (`default_branch`)

The default branch for new major versions.

**Default:** `"main"`

**Example:**
```toml
[branch_policy]
default_branch = "main"
```

### Create Branches (`create_branches`)

Whether to automatically create release branches if they don't exist.

**Default:** `true`

**Example:**
```toml
[branch_policy]
create_branches = true
```

### Branch From Previous Release (`branch_from_previous_release`)

Whether new minor versions should branch from the previous release branch.

**Default:** `true`

**Example:**
```toml
[branch_policy]
branch_from_previous_release = true
```

**Behavior:**
- `true`: 9.1.0 branches from release/9.0 (enables hotfix workflow)
- `false`: 9.1.0 branches from main

## Release Notes Policy

Controls categorization, formatting, and content of release notes.

### Documentation Release Version Policy (`documentation_release_version_policy`)

**NEW in v1.5**: Controls how documentation files are generated for release candidates.

**Options:** `"final-only"`, `"include-rcs"`

**Default:** `"final-only"`

**Scope:** Only affects `doc_output_path` (documentation files), NOT `release_output_path` (GitHub release notes)

**Example:**
```toml
[release_notes]
documentation_release_version_policy = "final-only"
```

#### "final-only" Mode (Default)

Generate documentation as if it were the final version:
- **Filename**: RC documentation uses final version name (e.g., `11.0.0.md` for `11.0.0-rc.1`)
- **Content**: Compares against previous final version (e.g., `10.x.x`)
- **Behavior**: Each RC overwrites the same file, building cumulative changelog
- **Final version**: Uses same file with complete changelog
- **GitHub release notes**: Still use standard comparison (RC.1 vs RC.0)

**Example workflow for version 11.0.0:**

| Action | Doc File | Doc Compares | GitHub Release | GitHub Compares |
|--------|----------|--------------|----------------|-----------------|
| Generate 11.0.0-rc.0 | `11.0.0.md` | 10.5.0 → 11.0.0-rc.0 | `11.0.0-rc.0` | 10.5.0 → 11.0.0-rc.0 |
| Generate 11.0.0-rc.1 | `11.0.0.md` (overwrites) | 10.5.0 → 11.0.0-rc.1 | `11.0.0-rc.1` | 11.0.0-rc.0 → 11.0.0-rc.1 |
| Generate 11.0.0 | `11.0.0.md` (overwrites) | 10.5.0 → 11.0.0 | `11.0.0` | 10.5.0 → 11.0.0 |

**Use Cases:**
- Docusaurus/versioned docs where you want one file per version
- Documentation that shows complete upcoming release changes
- Avoid RC clutter in documentation

#### "include-rcs" Mode

Generate separate documentation files for each RC:
- **Filename**: RC documentation includes RC suffix (e.g., `11.0.0-rc.1.md`)
- **Content**: Uses standard version comparison (RC.1 vs RC.0 or previous final)
- **Behavior**: Each RC generates a separate file
- **Final version**: Generates own file (`11.0.0.md`) with complete changelog
- **GitHub release notes**: Use standard comparison

**Example workflow for version 11.0.0:**

| Action | Doc File | Doc Compares | GitHub Release | GitHub Compares |
|--------|----------|--------------|----------------|-----------------|
| Generate 11.0.0-rc.0 | `11.0.0-rc.0.md` | 10.5.0 → 11.0.0-rc.0 | `11.0.0-rc.0` | 10.5.0 → 11.0.0-rc.0 |
| Generate 11.0.0-rc.1 | `11.0.0-rc.1.md` | 11.0.0-rc.0 → 11.0.0-rc.1 | `11.0.0-rc.1` | 11.0.0-rc.0 → 11.0.0-rc.1 |
| Generate 11.0.0 | `11.0.0.md` | 10.5.0 → 11.0.0 | `11.0.0` | 10.5.0 → 11.0.0 |

**Use Cases:**
- Document each RC separately for detailed tracking
- RCs deployed to different environments needing separate docs
- Keep history of what changed in each release candidate

### Categories

Define how release notes are grouped and ordered by labels.

**Example:**
```toml
[[release_notes.categories]]
name = "🚀 Features"
labels = ["feature", "enhancement"]
order = 1
alias = "features"
```

### Excluded Labels

Labels that exclude items from release notes entirely.

**Default:** `["skip-changelog", "internal", "wip", "do-not-merge"]`

**Example:**
```toml
[release_notes]
excluded_labels = ["skip-changelog", "internal"]
```

### Templates

Jinja2 templates for customizing release note output:
- **`title_template`**: Release title
- **`entry_template`**: Individual note entry
- **`release_output_template`**: GitHub release notes structure
- **`doc_output_template`**: Documentation output wrapper (e.g., Docusaurus frontmatter)

See [Configuration](configuration.md) for template details.

## Output Policy

Defines where and how release notes are published.

### Create GitHub Release (`create_github_release`)

Whether to create a GitHub release.

**Default:** `true`

**Example:**
```toml
[output]
create_github_release = true
```

### Create PR (`create_pr`)

Whether to create a PR with release notes file.

**Default:** `true`

**Example:**
```toml
[output]
create_pr = true
```

### Release Mode (`release_mode`)

Default mode for GitHub releases.

**Options:** `"draft"`, `"published"`

**Default:** `"draft"`

**Example:**
```toml
[output]
release_mode = "draft"
```

### Prerelease Detection (`prerelease`)

How to mark GitHub releases as prereleases.

**Options:** `"auto"`, `true`, `false`

**Default:** `"auto"`

**Example:**
```toml
[output]
prerelease = "auto"
```

**Behavior:**
- `"auto"`: Detect from version (e.g., `1.0.0-rc.1` → prerelease, `1.0.0` → stable)
- `true`: Always mark as prerelease
- `false`: Always mark as stable

### Create Issue (`create_issue`)

Whether to create a tracking issue for the release.

**Default:** `true`

**Example:**
```toml
[output]
create_issue = true
```

## Policy Best Practices

### Recommended Configuration for Most Teams

```toml
[version_policy]
gap_detection = "warn"

[issue_policy]
no_issue_action = "warn"
unclosed_issue_action = "warn"
partial_issue_action = "warn"
inter_release_duplicate_action = "warn"
consolidation_enabled = true
release_notes_inclusion_policy = ["issues", "pull-requests"]

[release_notes]
documentation_release_version_policy = "final-only"

[output]
release_mode = "draft"
prerelease = "auto"
```

### Strict Mode (Enforce All Rules)

```toml
[version_policy]
gap_detection = "error"

[issue_policy]
no_issue_action = "error"
unclosed_issue_action = "error"
partial_issue_action = "error"
inter_release_duplicate_action = "error"
consolidation_enabled = true
release_notes_inclusion_policy = ["issues"]
```

### Relaxed Mode (Minimal Enforcement)

```toml
[version_policy]
gap_detection = "ignore"

[issue_policy]
no_issue_action = "ignore"
unclosed_issue_action = "ignore"
partial_issue_action = "ignore"
inter_release_duplicate_action = "ignore"
consolidation_enabled = true
release_notes_inclusion_policy = ["issues", "pull-requests", "commits"]
```
