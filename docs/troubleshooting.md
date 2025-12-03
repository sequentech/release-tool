<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
sidebar_position: 6
---

# Troubleshooting

Common issues and how to resolve them.

## GitHub API Rate Limit

**Issue**: The tool fails with a 403 or 429 error when syncing.

**Cause**: You have exceeded the GitHub API rate limit.

**Solution**:
- Ensure you have configured a `GITHUB_TOKEN`. Authenticated requests have a much higher rate limit (5000/hour) than unauthenticated ones (60/hour).
- Check your token permissions.

## Missing Tickets in Release Notes

**Issue**: PRs are showing up in "Other" or not appearing at all.

**Cause**:
- The PR title or body does not contain a valid ticket reference (e.g., `JIRA-123`).
- The `ticket_patterns` configuration does not match your ticket format.
- The PR is not closed/merged.

**Solution**:
- Verify the PR has a ticket reference.
- Check your `release_tool.toml` configuration for `ticket_patterns`.
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
