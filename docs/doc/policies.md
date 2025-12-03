---
id: policies
title: Policies
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Policies

The Release Tool uses various policies to control its behavior. These policies can be configured to match your workflow. See the [Configuration](configuration.md) guide for details on how to set them up in `release_tool.toml`.

## Version Policy

Determines the next version number based on the changes since the last release.

- **Semantic Versioning**: Adheres to SemVer 2.0.0.
- **Gap Handling**: Configurable behavior when version gaps are detected (Ignore, Warn, Error).

## Ticket Policy

Extracts ticket information from Pull Requests and commits.

- **Extraction**: Finds ticket references (e.g., `JIRA-123`) in PR titles and bodies.
- **Info Retrieval**: Fetches ticket details like title, description, and type.
- **Consolidation**: Groups multiple commits belonging to the same parent ticket.

## Release Note Policy

Controls how release notes are generated and formatted.

- **Grouping**: Groups notes by category (e.g., Features, Bug Fixes).
- **Ordering**: Defines the order of categories.
- **Exclusions**: Excludes specific labels or tickets from the notes.
- **Templates**: Uses Jinja2 templates for the release note output.

## Output Policy

Defines where the generated release notes are published.

- **GitHub Release**: Updates the body of the GitHub release.
- **File Generation**: Creates a new markdown file in the repository (e.g., `CHANGELOG.md` or `releases/v1.0.0.md`).
