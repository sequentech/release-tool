---
id: release-bot
title: Release Bot
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Release Bot

Release Bot is a GitHub Action that automates your release workflow by integrating release-tool directly into GitHub Actions.

## Overview

The Release Bot provides three main automation features:

1. **Manual Release Generation** - Create and push releases via GitHub Actions workflow dispatch
2. **ChatOps Integration** - Control releases through PR and Issue comments
3. **Automatic Pushing** - Auto-push releases when PRs merge or issues close

## Setup

### 1. Install Release Bot

Add the workflow file to your repository at `.github/workflows/release.yml`:

```yaml
name: Release Workflow

on:
  workflow_dispatch:
    inputs:
      new_version_type:
        description: 'Auto-bump type (for generate)'
        required: false
        type: choice
        options:
          - none
          - patch
          - minor
          - major
          - rc
      version:
        description: 'Specific version (e.g., 1.2.0)'
        required: false
      from_version:
        description: 'Compare from this version'
        required: false
      force:
        description: 'Force overwrite'
        required: false
        default: 'none'
        type: choice
        options:
          - none
          - draft
          - published
      debug:
        description: 'Enable debug output'
        required: false
        default: false
        type: boolean

  issue_comment:
    types: [created]

  pull_request:
    types: [closed]
    branches:
      - 'release/**'

  issues:
    types: [closed]

jobs:
  release-bot:
    if: github.event_name != 'issue_comment' || startsWith(github.event.comment.body, '/release-bot ')
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: write
      pull-requests: write
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v3

      - name: Run Release Bot
        uses: sequentech/release-bot@v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          version: ${{ inputs.version }}
          new_version_type: ${{ inputs.new_version_type }}
          from_version: ${{ inputs.from_version }}
          force: ${{ inputs.force }}
          debug: ${{ inputs.debug }}
```

### 2. Configure Release Tool

Ensure you have a `.release_tool.toml` file in your repository root. See [Configuration](configuration.md) for details.

## Usage

### Manual Workflow Dispatch

Trigger a release manually from the GitHub Actions tab:

1. Go to **Actions** → **Release Workflow**
2. Click **Run workflow**
3. Configure options:
   - **Auto-bump type**: Choose `patch`, `minor`, `major`, or `rc`
   - **Specific version**: Or enter exact version like `1.2.3`
   - **Force**: Overwrite existing releases if needed

The workflow will:
1. Sync latest data from GitHub
2. Generate release notes
3. Publish the release (respecting your config's `release_mode`)

### ChatOps Commands

Comment on Issues or Pull Requests with these commands:

#### `/release-bot update`

Regenerates and publishes release notes. Equivalent to manual trigger.

```
/release-bot update
```

**Use case**: You've added more commits/PRs and want to refresh the release notes.

**Workflow**: pull → generate → push

#### `/release-bot publish [version]`

Publishes a specific version or auto-detects from issue.

```
/release-bot publish
/release-bot publish 1.2.3
```

**Use case**: Ready to publish a prepared release.

#### `/release-bot merge [version]`

Merges the PR, marks the release as published, and closes the issue in one step.

```
/release-bot merge
/release-bot merge 1.2.3
/release-bot merge version=1.2 issue=42
```

**Use case**: Finalize a release by merging PR, publishing release, and closing tracking issue.

**Workflow**: merge PR → mark release published → close issue

**Auto-detection**:
1. Version from issue association or partial match
2. PR from issue references or release branch
3. Issue from version association

**Behavior**:
- Idempotent: Skips already-completed steps
- Safe: Shows clear status for each operation
- Flexible: Works with full or partial versions

**Version detection**:
1. Specified version parameter
2. Database lookup by issue number
3. Parse issue title (e.g., "✨ Prepare Release 1.2.3")
4. Extract from PR branch (e.g., `release/v1.2.3`)
5. Extract from PR title

#### `/release-bot generate [version]`

Generates release notes without pushing.

```
/release-bot generate
/release-bot generate 1.2.3
```

**Use case**: Preview release notes before pushing.

#### `/release-bot list`

Lists available draft releases ready to publish.

```
/release-bot list
```

### Automatic Pushing

The bot automatically publishes releases based on two triggers:

#### PR Merge Auto-Pushing

When a PR from a release branch is merged:

**Example**: PR from branch `release/1.2` → merges to `main`

**Bot Actions**:
1. Extract version from branch name using config pattern
   - Pattern is read from `branch_policy.release_branch_template` in `.release_tool.toml`
   - Default pattern: `release/{major}.{minor}` matches branches like `release/1.2`, `release/2.0`
   - Custom patterns supported: `release/v{major}.{minor}.{patch}` matches `release/v1.2.3`
   - Fallback: Parse PR title if branch doesn't match pattern
2. Search PR body for issue references:
   - Pattern 1 (closing): `closes #123`, `fixes #456`, `resolves #789`
   - Pattern 2 (related): `related to #123`, `see #456`, `issue #789`
   - Pattern 3 (bare): `#123`
3. Execute: `release-tool push 1.2.3 --release-mode just-push --issue 123`

**Just-Publish Mode**:
- ✅ Marks existing draft release as published
- ✅ Preserves all release properties (notes, name, target)
- ✅ No git tag operations
- ✅ Perfect for PR workflow where draft already exists
- ❌ Fails if no existing release found

**Typical Workflow**:
```
Manual trigger (draft) → PR created → PR merged → just-push
```

#### Issue Close Auto-Pushing

When an issue tagged as a release issue is closed:

**Example**: Issue #123 titled "✨ Prepare Release 1.2.3" → closed

**Bot Actions**:
1. Detect issue closure
2. Extract version from title or database
3. Execute: `release-tool push 1.2.3 --release-mode published`

**Published Mode**:
- Creates or updates full release
- Creates/pushes git tags if needed
- Updates release notes
- Suitable for manual control

## Release Modes

The bot uses three release modes depending on the context:

### Draft Mode

```bash
--release-mode draft
```

**Purpose**: Create non-public release for review

**Behavior**:
- Creates GitHub release with `draft: true`
- Not visible to public
- Allows review before pushing

**Use cases**:
- Preparing releases for review
- Staging changes before announcement

### Published Mode

```bash
--release-mode published
```

**Purpose**: Full release creation/update with all operations

**Behavior**:
- Creates or updates git tags (local + remote)
- Generates/updates release notes
- Publishes to GitHub (visible to public)
- Creates/updates all metadata

**Use cases**:
- First-time release creation
- Issue-triggered auto-pushing
- Manual publish with full control

**Example**:
```bash
release-tool push 1.2.3 --release-mode published
```

### Mark-Published Mode

```bash
--release-mode mark-published
```

**Purpose**: Mark existing draft as published without modifications

**Behavior**:
- ✅ Updates existing release: `draft: false`
- ✅ Preserves title, body, prerelease, target
- ✅ No tag creation/pushing
- ✅ No release notes regeneration
- ❌ Errors if release doesn't exist

**Use cases**:
- PR merge automation
- Pushing pre-prepared drafts
- Separating preparation from pushing

**Example**:
```bash
release-tool push 1.2.3 --release-mode mark-published
```

**Error handling**:
```
Error: No existing GitHub release found for v1.2.3
Use --release-mode published or draft to create a new release
```

## Complete Workflow Examples

### Example 1: Manual Release with PR Review

1. **Create Draft Release** (Manual trigger)
   ```
   Actions → Run workflow
   Version: 1.2.3
   Release mode: draft
   ```
   Result: Draft release created with notes

2. **Review in PR** (Automatic)
   Bot creates PR with release notes
   Team reviews changes

3. **Merge PR** (Automatic mark-published)
   PR merges → Bot runs:
   ```bash
   release-tool push 1.2.3 --release-mode mark-published
   ```
   Result: Draft marked as published

### Example 2: Quick Patch Release

1. **Generate and Publish** (Manual trigger)
   ```
   Actions → Run workflow
   Auto-bump: patch
   Force: none
   ```
   Result: Immediate published release

### Example 3: ChatOps Update Flow

1. **Initial Release** (ChatOps)
   ```
   Comment: /release-bot update
   ```
   Result: pull → generate → push

2. **Add More Changes** (Development)
   Merge more PRs/commits

3. **Refresh Release** (ChatOps)
   ```
   Comment: /release-bot update
   ```
   Result: Updated release with new changes

### Example 4: Issue-Driven Release

1. **Create Issue**
   Title: "✨ Prepare Release 1.2.3"

2. **Work on Release**
   Link PRs to issue with `closes #123`

3. **Close Issue**
   Issue closed → Bot auto-publishes v1.2.3

## Issue Association

The bot automatically associates issues with releases:

### PR Body Parsing

When analyzing a PR, the bot searches for issue references:

**Pattern 1 - Closing Keywords**:
```
closes #123
fixes #456
resolves #789
```

**Pattern 2 - Related Keywords**:
```
related to #123
see #456
issue #789
```

**Pattern 3 - Bare References**:
```
#123
```

### Database Storage

Associated issues are stored in the `release_issues` table:
- Links versions to issue numbers
- Enables version lookup from issues
- Tracks release preparation progress

## Configuration Options

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `github_token` | GitHub token for API access | Required |
| `version` | Specific version to release | Auto-detected |
| `new_version_type` | Auto-bump: patch/minor/major/rc | `none` |
| `from_version` | Compare from this version | Latest |
| `force` | Force overwrite: none/draft/published | `none` |
| `debug` | Enable verbose logging | `false` |
| `config_path` | Path to config file | `.release_tool.toml` |

### Config File Settings

Control default behavior in `.release_tool.toml`:

```toml
[output]
create_github_release = true
release_mode = "draft"  # or "published"
prerelease = "auto"

[branch_policy]
# Branch pattern for release branches (used by bot to detect PR merges)
release_branch_template = "release/{major}.{minor}"  # Default
# Other examples:
# release_branch_template = "release/v{major}.{minor}.{patch}"
# release_branch_template = "releases/{major}.{minor}"
```

**Branch Pattern Detection**: The bot uses `release_branch_template` to detect which PR merges should trigger auto-pushing. The template supports Jinja2-style placeholders:
- `{major}` - Major version number
- `{minor}` - Minor version number  
- `{patch}` - Patch version number

The bot converts this template to a regex pattern to match incoming PR branches.

## Troubleshooting

### PR Merge Doesn't Auto-Publish

**Symptoms**: PR merges but release not published

**Checks**:
1. Workflow has `on.pull_request` configured
2. Branch matches pattern: `release/**`
3. Draft release exists for that version
4. Check Actions logs for errors

**Solution**:
```yaml
on:
  pull_request:
    types: [closed]
    branches:
      - 'release/**'
```

### Issue Not Associated with Release

**Symptoms**: Bot can't find version from issue

**Checks**:
1. Issue title includes version: "✨ Prepare Release 1.2.3"
2. PRs reference issue: `closes #123`
3. Database synced: Run pull command

**Solution**: Manually specify version:
```
/release-bot publish 1.2.3
```

### Mark-Published Fails with "No existing release"

**Symptoms**: PR merge fails with error

**Cause**: No draft release exists yet

**Solution**: Create draft first:
```bash
release-tool generate 1.2.3
release-tool push 1.2.3 --release-mode draft
```

## Best Practices

### 1. Use Draft Mode for Preparation

Create drafts early, review before pushing:
```yaml
[output]
release_mode = "draft"
```

### 2. Consistent Branch Naming

Use clear branch patterns:
```
release/v1.2.3
release/1.2.3
hotfix/v1.2.4
```

### 3. Link PRs to Issues

Always reference issues in PR bodies:
```markdown
This PR implements feature X.

Closes #123
```

### 4. Review Before Merge

Use PR review process:
1. Bot creates draft + PR
2. Team reviews release notes
3. Merge PR → auto-publish

### 5. Enable Debug for Troubleshooting

When investigating issues:
```yaml
debug: true
```

## Security Considerations

### Token Permissions

The bot requires:
- `contents: write` - Create tags and releases
- `issues: write` - Comment on issues
- `pull-requests: write` - Comment on PRs

### Workflow Protection

Limit who can trigger manual workflows:
```yaml
on:
  workflow_dispatch:
    # Only allow specific users/teams
```

## See Also

- [Configuration](configuration.md) - Configure release-tool
- [Usage](usage.md) - Manual release-tool usage
- [Policies](policies.md) - Customize release note generation
- [Scenarios](scenarios.md) - Real-world examples
