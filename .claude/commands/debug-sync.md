<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
description: Debug sync issues with verbose output and diagnostics
---

Debug synchronization issues with detailed logging and GitHub API diagnostics.

Steps:
1. Check configuration is valid:
   ```bash
   cat release_tool.toml | grep -E "(code_repo|issue_repos|parallel_workers|cutoff_date)"
   ```

2. Verify GitHub token is set and valid:
   ```bash
   echo "Token set: $([ -n "$GITHUB_TOKEN" ] && echo 'YES' || echo 'NO')"
   gh api user  # Test token validity
   ```

3. Check GitHub rate limits before sync:
   ```bash
   gh api rate_limit | jq '.rate'
   ```
   - Show remaining requests
   - Show limit and reset time

4. Run sync and capture all output:
   ```bash
   poetry run release-tool sync 2>&1 | tee debug_sync.log
   ```

5. Analyze the log for issues:
   - **Errors**: Search for "[red]" or "Error" or "Warning"
   - **API failures**: GitHub exceptions, rate limiting
   - **Silent periods**: Gaps >2 seconds without output (performance issue)
   - **Progress**: Verify all phases show progress

6. Check database after sync:
   ```bash
   sqlite3 release_tool.db << EOF
   SELECT 'Repositories:', COUNT(*) FROM repositories;
   SELECT 'Issues:', COUNT(*) FROM issues;
   SELECT 'Pull Requests:', COUNT(*) FROM pull_requests;
   SELECT 'Releases:', COUNT(*) FROM releases;
   SELECT 'Sync Metadata:', * FROM sync_metadata;
   EOF
   ```

7. If sync fails or hangs:
   - Check network connectivity: `ping api.github.com`
   - Check GitHub status: `gh api https://www.githubstatus.com/api/v2/status.json`
   - Check repository access: `gh repo view OWNER/REPO`
   - Verify repository names in config match GitHub

8. Common issues and fixes:
   - **401 Unauthorized**: GITHUB_TOKEN invalid or expired
   - **404 Not Found**: Repository name wrong or no access
   - **403 Rate Limited**: Wait for rate limit reset or use different token
   - **No progress**: Missing console.print in github_utils.py or sync.py
   - **Slow search**: Not using Search API (check github_utils.py)
   - **Slow fetch**: parallel_workers too low (check config)

9. Report diagnostics:
   - Configuration status
   - Token validity
   - Rate limit usage
   - Database state
   - Errors found
   - Suggested fixes
