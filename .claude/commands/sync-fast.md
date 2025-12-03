<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
description: Fast sync with progress monitoring and timing statistics
---

Run a fast, parallelized sync of GitHub data (tickets, PRs, releases) with detailed progress monitoring.

Steps:
1. Check if `release_tool.toml` exists and has valid configuration
2. Verify GITHUB_TOKEN environment variable is set
3. Run sync command with timing:
   ```bash
   time poetry run release-tool sync
   ```
4. Monitor the output for:
   - Progress indicators (searching, filtering, fetching)
   - Parallel fetch progress bars
   - Final statistics (tickets, PRs, releases synced)
5. Report total time taken
6. If sync takes >60 seconds, suggest checking:
   - Network connectivity
   - GitHub rate limits: `gh api rate_limit`
   - Database size: `ls -lh release_tool.db`

Expected performance:
- Search phase: <5 seconds per repository
- Parallel fetch: 20 items/second with 20 workers
- Total for 1000 items: ~50-60 seconds
