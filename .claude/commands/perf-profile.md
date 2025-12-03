<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
description: Profile sync performance and identify bottlenecks
---

Profile the sync operation to identify performance bottlenecks and measure parallelization effectiveness.

Steps:
1. Check current configuration:
   ```bash
   grep -A 5 "\[sync\]" release_tool.toml
   ```
   - Show parallel_workers setting (should be 20)
   - Show cutoff_date if set

2. Run sync with detailed timing:
   ```bash
   time -v poetry run release-tool sync 2>&1 | tee sync_profile.log
   ```

3. Analyze the output for:
   - **Search phase timing**: How long "Searching for tickets/PRs" takes
   - **Filtering phase**: Time spent filtering against existing DB
   - **Parallel fetch timing**: Items/second throughput
   - **Progress gaps**: Any delays >2 seconds without feedback

4. Calculate metrics:
   - Total items fetched
   - Total time taken
   - Throughput (items/second)
   - Expected vs actual performance

5. Check GitHub API rate limit usage:
   ```bash
   gh api rate_limit
   ```
   - Show remaining requests
   - Show reset time
   - Calculate requests used during sync

6. Analyze database size and query performance:
   ```bash
   ls -lh release_tool.db
   sqlite3 release_tool.db "SELECT COUNT(*) FROM tickets;"
   sqlite3 release_tool.db "SELECT COUNT(*) FROM pull_requests;"
   ```

7. Report findings:
   - **Performance**: X items in Y seconds = Z items/sec
   - **Expected**: ~20 items/sec with 20 workers
   - **Bottlenecks**: If <15 items/sec, identify why:
     - Network latency?
     - Rate limiting?
     - Database write contention?
     - Sequential operations that should be parallel?

8. Suggestions for improvement:
   - If slow search: Using Search API? (check github_utils.py)
   - If slow fetch: Enough parallel workers? (check config)
   - If slow filter: DB indexes needed? (check db.py)
   - If no progress: Missing console.print statements?
