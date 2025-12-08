<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Release Tool - Claude Code Project Context

## Project Overview

This is **release-tool**, a comprehensive Python CLI tool for managing releases using semantic versioning. It automates release note generation by consolidating commits, fetching issue details from GitHub, and creating beautifully formatted release notes.

## Key Capabilities

- **Semantic Versioning**: Full support for versions, release candidates, betas, alphas
- **Issue Consolidation**: Groups commits by parent issues for cleaner release notes
- **GitHub Integration**: Syncs PRs, issues, releases via parallelized API calls
- **Local Git Analysis**: Analyzes commit history from local repositories
- **Template-based Output**: Jinja2 templates for customizable release notes
- **Performance Optimized**: 20 parallel workers, GitHub Search API, efficient caching

## Technology Stack

- **Python 3.10+** with type hints and Pydantic models
- **PyGithub** - GitHub API integration
- **GitPython** - Local Git operations
- **Click** - CLI framework
- **Rich** - Beautiful terminal output with progress bars
- **Jinja2** - Template rendering
- **SQLite** - Local caching database
- **pytest** - Testing framework

## Architecture

```
src/release_tool/
├── main.py          # CLI entry point (sync, generate, list-releases commands)
├── models.py        # Pydantic models (SemanticVersion, Commit, PR, Issue, Release)
├── config.py        # Configuration with validation
├── db.py            # SQLite database operations
├── git_ops.py       # Git operations (find commits, tags, version comparison)
├── github_utils.py  # GitHub API client (search, fetch, create releases/PRs)
├── sync.py          # Parallelized sync manager
├── policies.py      # Issue extraction, consolidation, categorization
└── media_utils.py   # Media download utilities
```

## Common Workflows

### 1. Initial Setup
```bash
release-tool init-config          # Create release_tool.toml
export GITHUB_TOKEN="ghp_..."    # Set GitHub token
# Edit release_tool.toml with your repo settings
```

### 2. Sync GitHub Data
```bash
release-tool pull                 # Sync issues, PRs, releases
```

### 3. Generate Release Notes
```bash
release-tool generate 2.0.0 \
  --repo-path ~/projects/myrepo \
  --output docs/releases/2.0.0.md
```

### 4. Create GitHub Release or PR
```bash
release-tool generate 2.0.0 \
  --repo-path ~/projects/myrepo \
  --upload                        # Creates GitHub release

release-tool generate 2.0.0 \
  --repo-path ~/projects/myrepo \
  --create-pr                     # Creates PR with release notes
```

## Performance Requirements (CRITICAL)

When working on this codebase, ALWAYS adhere to these performance principles:

### 1. Parallelize All Network Operations
- Use `ThreadPoolExecutor` with 20 workers for GitHub API calls
- Batch size: 100-200 items for optimal throughput
- GitHub rate limit: 5000/hour = safe to parallelize aggressively

### 2. Use GitHub Search API
- NEVER use PyGithub's lazy iteration (`for issue in repo.get_issues()`)
- ALWAYS use Search API (`gh.search_issues(query)`)
- Search API is 10-20x faster than iteration

### 3. Progress Feedback ALWAYS
- NEVER leave user waiting >2 seconds without feedback
- Show "Searching...", "Found X items", "Filtering...", "Fetching X/Y..."
- Use Rich progress bars for parallel operations

### 4. Example Pattern
```python
# BAD - Sequential iteration
for issue in repo.get_issues():  # Each iteration = network call
    process(issue)

# GOOD - Search API + parallel fetch
query = f"repo:{repo_name} is:issue"
issues = gh.search_issues(query)  # Fast
console.print(f"Searching for issues...")
console.print(f"Found {len(issues)} issues")

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(fetch_details, num) for num in issues]
    for future in as_completed(futures):
        # Process with progress bar
```

## Testing

Run tests with:
```bash
pytest                           # All tests
pytest tests/test_sync.py -v    # Specific module
pytest --cov=release_tool        # With coverage
```

Current coverage: 74 tests across all modules.

## Slash Commands Available

See `.claude/commands/` for custom slash commands:
- `/sync-fast` - Quick sync with monitoring
- `/generate-release` - Generate release notes workflow
- `/test-affected` - Run tests for modified modules
- `/lint-fix` - Auto-fix code quality issues
- `/perf-profile` - Profile sync performance
- `/debug-sync` - Debug sync with verbose output

## Important Files

- `release_tool.toml` - Configuration file (created by `init-config`)
- `release_tool.db` - SQLite cache (auto-created by `pull`)
- `.release_tool_cache/` - Cloned git repositories for offline access
- `docs/` - User documentation
- `tests/` - Comprehensive unit tests

## Documentation

- Main docs: `docs/`
- README: `README.md`
- Example configs: `examples/example_*.toml`
- Template docs: `examples/MASTER_TEMPLATE_FEATURE.md`, `examples/OUTPUT_TEMPLATE_EXAMPLES.md`

## Key Design Patterns

1. **Issue Consolidation**: Commits grouped by parent issue for cleaner notes
2. **Version Comparison**: RCs compare to previous RC, finals to previous final
3. **Incremental Sync**: Only fetch new items since last sync
4. **Parallel Everything**: All GitHub operations parallelized
5. **Template System**: Jinja2 with category-based grouping and custom sections
