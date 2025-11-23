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
poetry run release-tool sync sequentech/my-repo
```

This command fetches the latest Pull Requests and commits and stores them in `release_tool.db`.

### 2. Generate Release Notes

To generate release notes for a new version, use the `generate-notes` command. You need to specify the target version.

```bash
poetry run release-tool generate-notes 1.2.0
```

By default, the tool will try to determine the previous version automatically. You can also specify it manually:

```bash
poetry run release-tool generate-notes 1.2.0 --from-version 1.1.0
```

### 3. Review Output

The command will output the generated release notes to the console (or a file if configured). Review the notes to ensure all tickets are correctly categorized and formatted.

### 4. Create Release

Once you are satisfied with the notes, you can proceed to create the release on GitHub.

```bash
poetry run release-tool release 1.2.0
```

This will:
- Create a git tag `v1.2.0`.
- Create a GitHub release with the generated notes.

## Common Commands

| Command | Description |
|---------|-------------|
| `sync <repo>` | Syncs PRs and commits from GitHub. |
| `generate-notes <version>` | Generates release notes for the specified version. |
| `release <version>` | Creates a tag and release on GitHub. |
