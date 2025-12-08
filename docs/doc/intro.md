---
id: intro
title: Intro
---

<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Introduction

The **Release Tool** is a CLI application designed to manage releases using semantic versioning. It automates the process of generating release notes, managing versions, and interacting with GitHub.

## Features

- **Semantic Versioning**: Automatically determines the next version based on changes.
- **Release Notes Generation**: Groups and formats release notes from Pull Requests and issues.
- **Policy-Driven**: Highly configurable policies for versioning, issue extraction, and grouping.
- **GitHub Integration**: Pulls data from GitHub and creates releases.
- **GitHub Actions Bot**: Automate releases with ChatOps and auto-pushing ([Release Bot](release-bot.md)).
- **Multiple Release Modes**: Draft, published, and just-push modes for different workflows.
- **SQLite Storage**: Caches repository data locally for efficiency.

## Goals

- Efficient and flexible release management.
- Configurable to support different workflows.
- "Create once, run everywhere" philosophy with a single binary/script.
