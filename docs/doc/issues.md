---
id: issues
title: Issues
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Issues

Query and explore issues in your local database without needing an internet connection.

## Overview

The `issues` command allows you to search and inspect issues that have been synced from GitHub to your local database. This is particularly useful for:

- **Debugging partial issue matches** - Find out why a issue wasn't found during release note generation
- **Exploring issue data** - See what issues are available in your database
- **Exporting data** - Generate CSV reports of issues
- **Finding typos** - Use fuzzy matching to find issues with similar numbers
- **Offline access** - Query issues without internet connectivity

:::caution Prerequisites
This command only searches issues that have been synced. Make sure to run `release-tool sync` first to populate your local database.
:::

## Smart ISSUE_KEY Format

The `issues` command supports multiple smart formats for specifying issue numbers, making it easier and faster to query issues:

### Supported Formats

1. **Plain number**: `8624`
   - Searches for issue 8624 across all repositories

2. **Hash prefix**: `#8624`
   - Same as plain number, GitHub-style reference

3. **Repo name + number**: `meta#8624`
   - Searches for issue 8624 specifically in the "meta" repository
   - Automatically resolves short repo names (e.g., "meta" → "owner/meta")

4. **Full repo path + number**: `sequentech/meta#8624`
   - Searches for issue 8624 in the specified full repository path

5. **Proximity search with ~**: `8624~` or `meta#8624~`
   - Finds issues numerically close to 8624 (within ±20 by default)
   - Can be combined with repo specifications
   - Equivalent to using `--close-to 8624`

### Examples

```bash
# Find issue 8624 in any repository
release-tool issues 8624

# Find issue 8624 with # prefix
release-tool issues #8624

# Find issue 8624 only in 'meta' repo (short name)
release-tool issues meta#8624

# Find issue 8624 in specific full repository
release-tool issues sequentech/meta#8624

# Find issues close to 8624 (±20) in any repo
release-tool issues 8624~

# Find issues close to 8624 in 'meta' repo
release-tool issues meta#8624~

# Find issues close to 8624 in full repo path
release-tool issues sequentech/meta#8624~
```

:::tip Combining with Options
The smart format can be combined with other options. For example, `--repo` flag will override the repository parsed from the ISSUE_KEY:

```bash
# The --repo flag takes precedence
release-tool issues --repo sequentech/step meta#1024
```
:::

## Basic Usage

### Find a Specific Issue

Search for a issue by its exact key or number:

```bash
release-tool issues 8624
```

This will display the issue in a formatted table if found in your local database.

### Find Issue in Specific Repository

If the same issue number exists in multiple repositories, filter by repository:

```bash
release-tool issues 8624 --repo sequentech/meta
```

### List All Issues in a Repository

View all issues from a specific repository:

```bash
release-tool issues --repo sequentech/meta
```

By default, this shows 20 results. Use `--limit` to change this:

```bash
release-tool issues --repo sequentech/meta --limit 50
```

## Fuzzy Matching

### Find Issues Starting With a Prefix

Useful when you only remember the beginning of a issue number:

```bash
release-tool issues --starts-with 86
```

This finds all issues starting with "86" (e.g., 8624, 8625, 8650, 8653, etc.)

### Find Issues Ending With a Suffix

Useful when you remember the ending of a issue number:

```bash
release-tool issues --ends-with 24
```

This finds all issues ending with "24" (e.g., 8624, 7124, 1024, etc.)

### Find Issues Numerically Close to a Number

This is particularly useful for debugging partial matches or finding typos:

```bash
# Find issues within ±20 of 8624 (default range)
release-tool issues --close-to 8624

# Find issues within ±50 of 8624
release-tool issues --close-to 8624 --range 50
```

For example, if you had a typo in your branch name like `feat/meta-8634/main` instead of `feat/meta-8624/main`, this would help you find the correct issue:

```bash
release-tool issues --close-to 8634 --range 20
# Shows: 8624, 8625, 8650, ... (all issues in range 8614-8654)
```

## Output Formats

### Table Format (Default)

The default output is a formatted table with colors:

```bash
release-tool issues --repo sequentech/meta --limit 5
```

Output:
```
┏━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key  ┃ Repository       ┃ Title                  ┃ State ┃ URL                     ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 8624 │ sequentech/meta  │ Add dark mode to UI    │ open  │ https://github.com/...  │
│ 8625 │ sequentech/meta  │ Fix login bug          │ closed│ https://github.com/...  │
│ 8650 │ sequentech/meta  │ Update documentation   │ open  │ https://github.com/...  │
└──────┴──────────────────┴────────────────────────┴───────┴─────────────────────────┘

Showing 1-3 issues (all results)
```

Features:
- **Color coding**: Open issues in green, closed issues dimmed
- **Truncation**: Long titles and URLs are automatically truncated
- **Pagination info**: Shows which results you're viewing

### CSV Format

Export issues to CSV for analysis in spreadsheet applications:

```bash
release-tool issues --repo sequentech/meta --format csv > issues.csv
```

The CSV includes all fields:
- `id` - Database ID
- `repo_id` - Repository ID
- `number` - Issue number
- `key` - Issue key (may include prefix)
- `title` - Issue title
- `body` - Issue description (truncated to 500 chars)
- `state` - "open" or "closed"
- `labels` - JSON array of label names
- `url` - GitHub URL
- `created_at` - Creation timestamp (ISO format)
- `closed_at` - Closure timestamp (ISO format, empty if still open)
- `category` - Category (if assigned)
- `tags` - JSON object of tags
- `repo_full_name` - Repository full name (owner/repo)

:::tip CSV Output
Pipe the output to a file using `> issues.csv` or use it directly in shell scripts.
:::

## Pagination

Control how many results are shown and skip results for pagination:

### Limit Results

Show only the first N issues:

```bash
release-tool issues --repo sequentech/meta --limit 10
```

### Skip Results (Offset)

Skip the first N results:

```bash
release-tool issues --repo sequentech/meta --offset 20
```

### Combined Pagination

Get results 21-30:

```bash
release-tool issues --repo sequentech/meta --limit 10 --offset 20
```

## Debugging Partial Matches

When `release-tool generate` shows partial issue match warnings, use `query-issues` to investigate.

### Scenario 1: Issue Not Found

If you see:
```
⚠️  Found 1 partial issue match(es)

Issues not found in database (1):
  • 8853 (from branch feat/meta-8853/main, PR #2122)
    → Issue may be older than sync cutoff date
    → Issue may not exist (typo in branch/PR)
    → Sync may not have been run yet
```

**Investigation steps:**

1. Check if issue exists in any repo:
   ```bash
   release-tool issues 8853
   ```

2. Search for similar issue numbers:
   ```bash
   release-tool issues --close-to 8853 --range 50
   ```

3. Check issues ending with same digits:
   ```bash
   release-tool issues --ends-with 53
   ```

4. If not found, verify on GitHub or re-run sync:
   ```bash
   release-tool sync
   ```

### Scenario 2: Issue in Different Repo

If you see:
```
⚠️  Found 1 partial issue match(es)

Issues in different repository (1):
  • 8624 (from branch feat/meta-8624/main, PR #2122)
    Found in: sequentech/step
    URL: https://github.com/sequentech/step/issues/8624
```

**Investigation steps:**

1. Verify issue location:
   ```bash
   release-tool issues 8624
   ```

2. Check all repos for this issue:
   ```bash
   # Without --repo filter to see all matches
   release-tool issues 8624
   ```

3. Fix your branch name or config's `issue_repos` setting

### Scenario 3: Finding Typos in Branch Names

If your branch has a typo like `feat/meta-8643/main` but the real issue is `8624`:

```bash
# Find issues close to the typo
release-tool issues --close-to 8643 --range 30

# This will show issues like 8624, 8625, 8650, etc.
# helping you identify the correct issue number
```

## Advanced Examples

### Combine Filters

Find issues ending with "24" in a specific repo:

```bash
release-tool issues --ends-with 24 --repo sequentech/step
```

### Export Filtered Results

Export all open issues to CSV:

```bash
# First, find them in table format
release-tool issues --repo sequentech/meta --limit 100

# Then export to CSV
release-tool issues --repo sequentech/meta --limit 100 --format csv > open_issues.csv
```

### Check Database Contents

See what's in your database:

```bash
# List recent issues across all repos
release-tool issues --limit 50

# List issues from each repo
release-tool issues --repo sequentech/meta --limit 20
release-tool issues --repo sequentech/step --limit 20
```

## Options Reference

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `issue_key` | - | Exact issue key to search (positional argument) | - |
| `--repo` | `-r` | Filter by repository (owner/repo format) | All repos |
| `--limit` | `-n` | Maximum number of results | 20 |
| `--offset` | - | Skip first N results (for pagination) | 0 |
| `--format` | `-f` | Output format: `table` or `csv` | table |
| `--starts-with` | - | Find issues starting with prefix (fuzzy) | - |
| `--ends-with` | - | Find issues ending with suffix (fuzzy) | - |
| `--close-to` | - | Find issues numerically close to number | - |
| `--range` | - | Range for `--close-to` (±N) | 20 |

## Validation Rules

- `--range` must be >= 0
- `--limit` must be > 0
- `--offset` must be >= 0
- Cannot combine `--close-to` with `--starts-with` or `--ends-with`
- `--range` is only valid with `--close-to`

## Tips and Tricks

### 1. Quick Issue Lookup

Add a shell alias for quick lookups:

```bash
# In your ~/.bashrc or ~/.zshrc
alias qt='release-tool issues'

# Then use it:
qt 8624
qt --repo sequentech/meta
```

### 2. Pipeline with grep

Filter table output with grep:

```bash
release-tool issues --repo sequentech/meta | grep "bug"
```

### 3. Count Issues

Count issues in a repo using CSV and wc:

```bash
release-tool issues --repo sequentech/meta --limit 1000 --format csv | wc -l
```

### 4. Find Recently Synced Issues

Since results are sorted by `created_at DESC`, the first results show the newest issues:

```bash
release-tool issues --limit 10
```

### 5. Verify Sync Coverage

Check if issues from a specific time period are synced:

```bash
# Export all issues with timestamps
release-tool issues --limit 1000 --format csv > all_issues.csv

# Then inspect created_at dates in a spreadsheet
```

## Troubleshooting

### "Database not found"

**Error:**
```
Error: Database not found. Please run 'release-tool sync' first.
```

**Solution:**
```bash
release-tool sync
```

The database is created by the `sync` command. If you've never synced, the database doesn't exist yet.

### "Repository 'X' not found in database"

**Error:**
```
Error: Repository 'sequentech/unknown' not found in database.
Tip: Run 'release-tool sync' to fetch repository data.
```

**Solutions:**
1. Check the repository name spelling
2. Ensure the repository is configured in `release_tool.toml`
3. Run `release-tool sync` to fetch repository metadata

### No Results Found

If your query returns no results:

1. Verify issues exist on GitHub
2. Check your sync cutoff date (might be excluding old issues)
3. Re-run sync: `release-tool sync`
4. Try fuzzy matching instead of exact match

### CSV Output Looks Wrong in Terminal

CSV is designed for file output, not terminal display:

```bash
# Instead of this:
release-tool issues --format csv

# Do this:
release-tool issues --format csv > issues.csv
```

## See Also

- [Usage Guide](usage.md) - General workflow including sync
- [Troubleshooting](troubleshooting.md) - Common issues
- [Configuration](configuration.md) - Config file reference
