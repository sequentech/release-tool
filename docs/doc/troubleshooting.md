---
id: troubleshooting
title: Troubleshooting
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Troubleshooting

Common issues and how to resolve them.

## GitHub API Rate Limit

**Issue**: The tool fails with a 403 or 429 error when syncing.

**Cause**: You have exceeded the GitHub API rate limit.

**Solution**:
- Ensure you have configured a `GITHUB_TOKEN`. Authenticated requests have a much higher rate limit (5000/hour) than unauthenticated ones (60/hour).
- Check your token permissions.

## Missing Issues in Release Notes

**Issue**: PRs are showing up in "Other" or not appearing at all.

**Cause**:
- The PR title or body does not contain a valid issue reference (e.g., `JIRA-123`).
- The `issue_patterns` configuration does not match your issue format.
- The PR is not closed/merged.

**Solution**:
- Verify the PR has a issue reference.
- Check your `release_tool.toml` configuration for `issue_patterns`.
- Ensure the PR is merged.

## Database Locked

**Issue**: `sqlite3.OperationalError: database is locked`.

**Cause**: Another process is accessing the `release_tool.db` file.

**Solution**:
- Ensure no other instance of the tool is running.
- Check if an IDE or database viewer has the file open.

## Version Gap Warning

**Issue**: The tool warns about a version gap (e.g., releasing `1.3.0` when previous is `1.1.0`).

**Cause**: You might have skipped a version number.

**Solution**:
- Verify the version number is correct.
- If intentional, you can ignore the warning or configure the `version_gap_policy` to `ignore`.

## Git Clone Authentication Issues

### Empty Token Error (`https://@github.com/...`)

**Issue**: Git clone fails with error: `Command '['git', 'clone', 'https://@github.com/...']' returned non-zero exit status 128`.

**Cause**: The `GITHUB_TOKEN` environment variable is set but empty, resulting in an invalid clone URL.

**Solution**:
- Ensure `GITHUB_TOKEN` is properly set:
  ```bash
  export GITHUB_TOKEN="ghp_your_token_here"
  ```
- In GitHub Actions, verify the token is passed correctly:
  ```yaml
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  ```
- Check your workflow has proper permissions:
  ```yaml
  permissions:
    contents: read
    issues: read
    pull-requests: read
  ```

### Permission Denied (Private Repositories)

**Issue**: Git clone fails with "Permission denied" or "repository not found" error.

**Cause**: The GitHub token doesn't have access to the repository, or SSH keys are not configured.

**Solution**:

For HTTPS (recommended for GitHub Actions):
1. Verify your token has `contents: read` permission
2. For private repos, ensure the token can access the repository
3. Configure the clone method:
   ```toml
   [sync]
   clone_method = "https"  # or "auto" (default)
   ```

For SSH (local development):
1. Ensure SSH keys are configured: `ssh -T git@github.com`
2. Configure the clone method:
   ```toml
   [sync]
   clone_method = "ssh"
   ```
3. In GitHub Actions, use the SSH agent:
   ```yaml
   - name: Setup SSH
     uses: webfactory/ssh-agent@v0.9.0
     with:
       ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}
   ```

### GitHub Actions Clone Failures

**Issue**: Repository cloning fails in GitHub Actions workflows.

**Cause**: Missing permissions or incorrect token configuration.

**Solution**:
1. Add required permissions to your workflow:
   ```yaml
   permissions:
     contents: read  # Required for cloning
     issues: read
     pull-requests: read
   ```

2. Pass the token to the release-tool:
   ```yaml
   - name: Sync repository data
     env:
       GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
     run: release-tool sync
   ```

3. Use `clone_method = "auto"` (default) or `"https"` in your config:
   ```toml
   [sync]
   clone_method = "auto"
   ```

### GitHub Enterprise

**Issue**: Cannot clone from GitHub Enterprise server.

**Cause**: Using default GitHub.com URLs.

**Solution**:
1. Configure custom API URL and clone template:
   ```toml
   [github]
   api_url = "https://github.enterprise.com/api/v3"

   [sync]
   clone_url_template = "https://github.enterprise.com/{repo_full_name}.git"
   ```

2. Ensure your token has access to the Enterprise instance.
