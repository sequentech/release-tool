<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

---
sidebar_position: 1
---

# Introduction

The **Release Tool** is a CLI application designed to manage releases using semantic versioning. It automates the process of generating release notes, managing versions, and interacting with GitHub.

## Features

- **Semantic Versioning**: Automatically determines the next version based on changes.
- **Release Notes Generation**: Groups and formats release notes from Pull Requests and tickets.
- **Policy-Driven**: Highly configurable policies for versioning, ticket extraction, and grouping.
- **GitHub Integration**: Syncs data from GitHub and creates releases.
- **SQLite Storage**: Caches repository data locally for efficiency.

## Goals

- Efficient and flexible release management.
- Configurable to support different workflows.
- "Create once, run everywhere" philosophy with a single binary/script.
