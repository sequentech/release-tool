---
id: scenarios
title: Scenarios
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Scenarios

This section covers different scenarios you might encounter when using the Release Tool.

## Scenario 1: Standard Release

**Context**: You are releasing a regular update (e.g., `1.2.0`) that includes several feature PRs and bug fixes.

**Steps**:
1.  Sync the repo: `release-tool sync sequentech/app`
2.  Generate notes: `release-tool generate-notes 1.2.0`
3.  Release: `release-tool release 1.2.0`

**Outcome**: A new release `v1.2.0` is created on GitHub with categorized notes.

## Scenario 2: Hotfix Release

**Context**: You need to release a critical bug fix (e.g., `1.2.1`) immediately.

**Steps**:
1.  Sync the repo: `release-tool sync sequentech/app`
2.  Generate notes: `release-tool generate-notes 1.2.1 --from-version 1.2.0`
    *   *Note: Explicitly setting the previous version ensures only the hotfix changes are included.*
3.  Release: `release-tool release 1.2.1`

## Scenario 3: First Release

**Context**: You are releasing the very first version of a project (e.g., `1.0.0`).

**Steps**:
1.  Sync the repo.
2.  Generate notes: `release-tool generate-notes 1.0.0`
    *   *The tool will detect there are no previous versions and include all history up to this point.*
3.  Release: `release-tool release 1.0.0`

## Scenario 4: Release Candidate

**Context**: You are preparing a release candidate (e.g., `2.0.0-rc.1`).

**Steps**:
1.  Sync the repo.
2.  Generate notes: `release-tool generate-notes 2.0.0-rc.1`
3.  Release: `release-tool release 2.0.0-rc.1`

**Subsequent RC**:
When releasing `2.0.0-rc.2`, the tool will compare it against `2.0.0-rc.1`.

**Final Release**:
When releasing `2.0.0` (final), the tool will consolidate changes from all RCs (`rc.1`, `rc.2`) and compare against the previous stable version (e.g., `1.5.0`), providing a comprehensive changelog.
