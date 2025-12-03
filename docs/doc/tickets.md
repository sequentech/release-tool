---
id: tickets
title: Tickets
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Tickets

Query and explore tickets in your local database without needing an internet connection.

## Overview

The `tickets` command allows you to search and inspect tickets that have been synced from GitHub to your local database. This is particularly useful for:

- **Debugging partial ticket matches** - Find out why a ticket wasn't found during release note generation
- **Exploring ticket data** - See what tickets are available in your database
- **Exporting data** - Generate CSV reports of tickets
- **Finding typos** - Use fuzzy matching to find tickets with similar numbers
- **Offline access** - Query tickets without internet connectivity

:::caution Prerequisites
This command only searches tickets that have been synced. Make sure to run `release-tool sync` first to populate your local database.
:::

## Smart TICKET_KEY Format

The `tickets` command supports multiple smart formats for specifying ticket numbers, making it easier and faster to query tickets:

### Supported Formats

1. **Plain number**: `8624`
   - Searches for ticket 8624 across all repositories

2. **Hash prefix**: `#8624`
   - Same as plain number, GitHub-style reference

3. **Repo name + number**: `meta#8624`
   - Searches for ticket 8624 specifically in the "meta" repository
   - Automatically resolves short repo names (e.g., "meta" → "owner/meta")

4. **Full repo path + number**: `sequentech/meta#8624`
   - Searches for ticket 8624 in the specified full repository path

5. **Proximity search with ~**: `8624~` or `meta#8624~`
   - Finds tickets numerically close to 8624 (within ±20 by default)
   - Can be combined with repo specifications
   - Equivalent to using `--close-to 8624`

### Examples

```bash
# Find ticket 8624 in any repository
release-tool tickets 8624

# Find ticket 8624 with # prefix
release-tool tickets #8624

# Find ticket 8624 only in 'meta' repo (short name)
release-tool tickets meta#8624

# Find ticket 8624 in specific full repository
release-tool tickets sequentech/meta#8624

# Find tickets close to 8624 (±20) in any repo
release-tool tickets 8624~

# Find tickets close to 8624 in 'meta' repo
release-tool tickets meta#8624~

# Find tickets close to 8624 in full repo path
release-tool tickets sequentech/meta#8624~
```

:::tip Combining with Options
The smart format can be combined with other options. For example, `--repo` flag will override the repository parsed from the TICKET_KEY:

```bash
# The --repo flag takes precedence
release-tool tickets --repo sequentech/step meta#1024
```
:::

## Basic Usage

### Find a Specific Ticket

Search for a ticket by its exact key or number:

```bash
release-tool tickets 8624
```

This will display the ticket in a formatted table if found in your local database.

### Find Ticket in Specific Repository

If the same ticket number exists in multiple repositories, filter by repository:

```bash
release-tool tickets 8624 --repo sequentech/meta
```

### List All Tickets in a Repository

View all tickets from a specific repository:

```bash
release-tool tickets --repo sequentech/meta
```

By default, this shows 20 results. Use `--limit` to change this:

```bash
release-tool tickets --repo sequentech/meta --limit 50
```

## Fuzzy Matching

### Find Tickets Starting With a Prefix

Useful when you only remember the beginning of a ticket number:

```bash
release-tool tickets --starts-with 86
```

This finds all tickets starting with "86" (e.g., 8624, 8625, 8650, 8653, etc.)

### Find Tickets Ending With a Suffix

Useful when you remember the ending of a ticket number:

```bash
release-tool tickets --ends-with 24
```

This finds all tickets ending with "24" (e.g., 8624, 7124, 1024, etc.)

### Find Tickets Numerically Close to a Number

This is particularly useful for debugging partial matches or finding typos:

```bash
# Find tickets within ±20 of 8624 (default range)
release-tool tickets --close-to 8624

# Find tickets within ±50 of 8624
release-tool tickets --close-to 8624 --range 50
```

For example, if you had a typo in your branch name like `feat/meta-8634/main` instead of `feat/meta-8624/main`, this would help you find the correct ticket:

```bash
release-tool tickets --close-to 8634 --range 20
# Shows: 8624, 8625, 8650, ... (all tickets in range 8614-8654)
```

## Output Formats

### Table Format (Default)

The default output is a formatted table with colors:

```bash
release-tool tickets --repo sequentech/meta --limit 5
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

Showing 1-3 tickets (all results)
```

Features:
- **Color coding**: Open tickets in green, closed tickets dimmed
- **Truncation**: Long titles and URLs are automatically truncated
- **Pagination info**: Shows which results you're viewing

### CSV Format

Export tickets to CSV for analysis in spreadsheet applications:

```bash
release-tool tickets --repo sequentech/meta --format csv > tickets.csv
```

The CSV includes all fields:
- `id` - Database ID
- `repo_id` - Repository ID
- `number` - Ticket number
- `key` - Ticket key (may include prefix)
- `title` - Ticket title
- `body` - Ticket description (truncated to 500 chars)
- `state` - "open" or "closed"
- `labels` - JSON array of label names
- `url` - GitHub URL
- `created_at` - Creation timestamp (ISO format)
- `closed_at` - Closure timestamp (ISO format, empty if still open)
- `category` - Category (if assigned)
- `tags` - JSON object of tags
- `repo_full_name` - Repository full name (owner/repo)

:::tip CSV Output
Pipe the output to a file using `> tickets.csv` or use it directly in shell scripts.
:::

## Pagination

Control how many results are shown and skip results for pagination:

### Limit Results

Show only the first N tickets:

```bash
release-tool tickets --repo sequentech/meta --limit 10
```

### Skip Results (Offset)

Skip the first N results:

```bash
release-tool tickets --repo sequentech/meta --offset 20
```

### Combined Pagination

Get results 21-30:

```bash
release-tool tickets --repo sequentech/meta --limit 10 --offset 20
```

## Debugging Partial Matches

When `release-tool generate` shows partial ticket match warnings, use `query-tickets` to investigate.

### Scenario 1: Ticket Not Found

If you see:
```
⚠️  Found 1 partial ticket match(es)

Tickets not found in database (1):
  • 8853 (from branch feat/meta-8853/main, PR #2122)
    → Ticket may be older than sync cutoff date
    → Ticket may not exist (typo in branch/PR)
    → Sync may not have been run yet
```

**Investigation steps:**

1. Check if ticket exists in any repo:
   ```bash
   release-tool tickets 8853
   ```

2. Search for similar ticket numbers:
   ```bash
   release-tool tickets --close-to 8853 --range 50
   ```

3. Check tickets ending with same digits:
   ```bash
   release-tool tickets --ends-with 53
   ```

4. If not found, verify on GitHub or re-run sync:
   ```bash
   release-tool sync
   ```

### Scenario 2: Ticket in Different Repo

If you see:
```
⚠️  Found 1 partial ticket match(es)

Tickets in different repository (1):
  • 8624 (from branch feat/meta-8624/main, PR #2122)
    Found in: sequentech/step
    URL: https://github.com/sequentech/step/issues/8624
```

**Investigation steps:**

1. Verify ticket location:
   ```bash
   release-tool tickets 8624
   ```

2. Check all repos for this ticket:
   ```bash
   # Without --repo filter to see all matches
   release-tool tickets 8624
   ```

3. Fix your branch name or config's `ticket_repos` setting

### Scenario 3: Finding Typos in Branch Names

If your branch has a typo like `feat/meta-8643/main` but the real ticket is `8624`:

```bash
# Find tickets close to the typo
release-tool tickets --close-to 8643 --range 30

# This will show tickets like 8624, 8625, 8650, etc.
# helping you identify the correct ticket number
```

## Advanced Examples

### Combine Filters

Find tickets ending with "24" in a specific repo:

```bash
release-tool tickets --ends-with 24 --repo sequentech/step
```

### Export Filtered Results

Export all open tickets to CSV:

```bash
# First, find them in table format
release-tool tickets --repo sequentech/meta --limit 100

# Then export to CSV
release-tool tickets --repo sequentech/meta --limit 100 --format csv > open_tickets.csv
```

### Check Database Contents

See what's in your database:

```bash
# List recent tickets across all repos
release-tool tickets --limit 50

# List tickets from each repo
release-tool tickets --repo sequentech/meta --limit 20
release-tool tickets --repo sequentech/step --limit 20
```

## Options Reference

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `ticket_key` | - | Exact ticket key to search (positional argument) | - |
| `--repo` | `-r` | Filter by repository (owner/repo format) | All repos |
| `--limit` | `-n` | Maximum number of results | 20 |
| `--offset` | - | Skip first N results (for pagination) | 0 |
| `--format` | `-f` | Output format: `table` or `csv` | table |
| `--starts-with` | - | Find tickets starting with prefix (fuzzy) | - |
| `--ends-with` | - | Find tickets ending with suffix (fuzzy) | - |
| `--close-to` | - | Find tickets numerically close to number | - |
| `--range` | - | Range for `--close-to` (±N) | 20 |

## Validation Rules

- `--range` must be >= 0
- `--limit` must be > 0
- `--offset` must be >= 0
- Cannot combine `--close-to` with `--starts-with` or `--ends-with`
- `--range` is only valid with `--close-to`

## Tips and Tricks

### 1. Quick Ticket Lookup

Add a shell alias for quick lookups:

```bash
# In your ~/.bashrc or ~/.zshrc
alias qt='release-tool tickets'

# Then use it:
qt 8624
qt --repo sequentech/meta
```

### 2. Pipeline with grep

Filter table output with grep:

```bash
release-tool tickets --repo sequentech/meta | grep "bug"
```

### 3. Count Tickets

Count tickets in a repo using CSV and wc:

```bash
release-tool tickets --repo sequentech/meta --limit 1000 --format csv | wc -l
```

### 4. Find Recently Synced Tickets

Since results are sorted by `created_at DESC`, the first results show the newest tickets:

```bash
release-tool tickets --limit 10
```

### 5. Verify Sync Coverage

Check if tickets from a specific time period are synced:

```bash
# Export all tickets with timestamps
release-tool tickets --limit 1000 --format csv > all_tickets.csv

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

1. Verify tickets exist on GitHub
2. Check your sync cutoff date (might be excluding old tickets)
3. Re-run sync: `release-tool sync`
4. Try fuzzy matching instead of exact match

### CSV Output Looks Wrong in Terminal

CSV is designed for file output, not terminal display:

```bash
# Instead of this:
release-tool tickets --format csv

# Do this:
release-tool tickets --format csv > tickets.csv
```

## See Also

- [Usage Guide](usage.md) - General workflow including sync
- [Troubleshooting](troubleshooting.md) - Common issues
- [Configuration](configuration.md) - Config file reference
