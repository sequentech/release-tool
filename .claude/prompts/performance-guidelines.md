<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Release Tool - Performance Guidelines

## Critical Performance Requirements

When working on this codebase, these performance principles are **MANDATORY**:

## 1. Parallelize ALL Network Operations

### Rule: GitHub API Calls Must Be Parallel

**Bad** - Sequential (NEVER do this):
```python
for issue_number in issue_numbers:
    issue = github.fetch_issue(repo, issue_number)  # Each call blocks
    process(issue)
```

**Good** - Parallel (ALWAYS do this):
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {
        executor.submit(github.fetch_issue, repo, num): num
        for num in issue_numbers
    }
    for future in as_completed(futures):
        issue = future.result()
        process(issue)
```

### Configuration
- **Workers**: 20 parallel workers (default in config.py:279)
- **Batch size**: 100-200 items per batch (github_utils.py:65)
- **Rate limit**: GitHub allows 5000 requests/hour = 83/minute
- **Safe**: 20 parallel workers ≈ 20 requests/second = well within limits

## 2. Use GitHub Search API (Not Lazy Iteration)

### Rule: NEVER Use PyGithub's Lazy Iteration

**Bad** - Lazy iteration (NEVER do this):
```python
# Each iteration makes a network call - EXTREMELY SLOW
for issue in repo.get_issues(state='all', since=cutoff_date):
    if issue.pull_request is None:
        issue_numbers.append(issue.number)
```

**Good** - Search API (ALWAYS do this):
```python
# Single fast API call with pagination handled by GitHub
query = f"repo:{repo_name} is:issue"
if cutoff_date:
    query += f" created:>={cutoff_date.strftime('%Y-%m-%d')}"

issues = gh.search_issues(query, sort='created', order='desc')
issue_numbers = [issue.number for issue in issues]
```

### Why Search API is Faster
- Lazy iteration: 1 network call per item = 1000 items = 1000 calls
- Search API: Paginated results = 1000 items = ~10 calls (100 per page)
- **Speed improvement: 10-100x faster**

## 3. CRITICAL: Use PyGithub raw_data (No Lazy Loading)

### Rule: NEVER Access PyGithub Object Attributes Directly in Bulk Operations

**CRITICAL PERFORMANCE RULE**: During bulk sync operations (issues, PRs, commits, etc.), accessing PyGithub object attributes directly triggers **individual API calls** for each attribute not in the partial response.

**Bad** - Direct attribute access (NEVER do this in bulk operations):
```python
def _issue_to_issue(self, gh_issue, repo_id):
    return Issue(
        number=gh_issue.number,
        title=gh_issue.title,        # ❌ LAZY LOAD - triggers API call!
        body=gh_issue.body,           # ❌ LAZY LOAD - triggers API call!
        state=gh_issue.state,         # ❌ LAZY LOAD - triggers API call!
        url=gh_issue.html_url,        # ❌ LAZY LOAD - triggers API call!
        created_at=gh_issue.created_at  # ❌ LAZY LOAD - triggers API call!
    )
# Result: Converting 100 issues = 500+ API calls = 2 MINUTES!
```

**Good** - Use raw_data dictionary (ALWAYS do this):
```python
def _issue_to_issue(self, gh_issue, repo_id):
    # Use raw_data to avoid lazy loading
    raw = getattr(gh_issue, 'raw_data', {})

    return Issue(
        number=gh_issue.number,       # ✅ Safe - always in partial response
        title=raw.get('title'),       # ✅ No API call - from raw_data
        body=raw.get('body'),         # ✅ No API call - from raw_data
        state=raw.get('state'),       # ✅ No API call - from raw_data
        url=raw.get('html_url'),      # ✅ No API call - from raw_data
        created_at=raw.get('created_at')  # ✅ No API call - from raw_data
    )
# Result: Converting 100 issues = 0 API calls = INSTANT!
```

### Applies To ALL PyGithub Objects
- **Issues**: `title`, `body`, `state`, `html_url`, `created_at`, `closed_at`, `labels`
- **Pull Requests**: `title`, `body`, `state`, `merged_at`, `base`, `head`, `labels`, `user`
- **Commits**: `message`, `author`, `committer`, `parents`
- **Labels**: `name`, `color`, `description`
- **Milestones**: `title`, `description`, `state`, `due_on`
- **Users**: `name`, `email`, `company`, `location`, `bio`, `blog`

### Extracting Nested Objects from raw_data
```python
# Labels - extract from raw_data list
raw = getattr(gh_pr, 'raw_data', {})
labels = []
for label_data in raw.get('labels', []):
    labels.append(Label(
        name=label_data.get('name', ''),
        color=label_data.get('color', ''),
        description=label_data.get('description')
    ))

# Nested objects (base/head for PRs)
base_data = raw.get('base', {})
head_data = raw.get('head', {})
base_branch = base_data.get('ref')
head_sha = head_data.get('sha')

# User objects - create mock with raw_data
user_data = raw.get('user')
if user_data:
    from types import SimpleNamespace
    gh_user = SimpleNamespace(
        login=user_data.get('login'),
        id=user_data.get('id'),
        raw_data=user_data
    )
```

### Performance Impact
- **Without raw_data**: 100 items = 500+ API calls = 2+ minutes
- **With raw_data**: 100 items = 0 extra API calls = <1 second
- **Speed improvement: 100-1000x faster**

## 4. Progress Feedback ALWAYS

### Rule: Never Leave User Waiting >2 Seconds Without Feedback

**Required feedback points**:
1. **Before network call**: "Searching for issues..."
2. **After search**: "Found 123 issues"
3. **Before filtering**: "Filtering 123 issues against existing 456 in database..."
4. **Before parallel fetch**: "Fetching 67 new issues in parallel..."
5. **During fetch**: Progress bar with "Fetched 13/67 issues (19%)"
6. **After fetch**: "✓ Synced 67 issues"

**Example implementation**:
```python
console.print("[cyan]Searching for issues...[/cyan]")
query = f"repo:{repo_name} is:issue"
issues = gh.search_issues(query)
console.print(f"[green]✓[/green] Found {len(issues)} issues")

if all_numbers:
    console.print(f"[dim]Filtering {len(all_numbers)} issues...[/dim]")
new_numbers = [n for n in all_numbers if n not in existing]

console.print(f"[cyan]Fetching {len(new_numbers)} new issues in parallel...[/cyan]")

with Progress(...) as progress:
    task = progress.add_task("Fetching issues...", total=len(new_numbers))
    for future in as_completed(futures):
        result = future.result()
        progress.update(task, advance=1, description=f"Fetched {completed}/{total}")
```

## 4. Batch Processing

### Optimal Batch Sizes
- **GitHub Search**: No batching needed (API handles pagination)
- **Parallel fetch**: 100-200 items per batch
- **Database writes**: Immediate (upsert as results arrive)

### Example
```python
batch_size = 100  # Optimal for GitHub API throughput

pr_batch = []
for pr in gh_prs:
    pr_batch.append(pr)

    if len(pr_batch) >= batch_size:
        batch_results = self._process_pr_batch(pr_batch)  # Parallel processing
        prs_data.extend(batch_results)
        pr_batch = []  # Reset batch
```

## 5. Incremental Sync

### Rule: Only Fetch New/Updated Items

**Bad** - Fetch everything every time:
```python
all_issues = fetch_all_issues()  # Wasteful
store_in_db(all_issues)
```

**Good** - Incremental with cutoff date:
```python
last_sync = db.get_last_sync(repo, 'issues')
cutoff_date = last_sync or config.sync.cutoff_date

# Only fetch items since last sync
query = f"repo:{repo_name} is:issue created:>={cutoff_date}"
new_issues = gh.search_issues(query)

# Filter out any we already have
existing_numbers = db.get_existing_issue_numbers(repo)
to_fetch = [n for n in new_issues if n not in existing_numbers]
```

## Performance Metrics

### Expected Performance
- **Search phase**: <5 seconds per repository
- **Filter phase**: <1 second (in-memory set operations)
- **Parallel fetch**: ~20 items/second with 20 workers
- **Total for 1000 items**: ~50-60 seconds

### Actual Performance Measurements
```bash
# Profile a sync
time poetry run release-tool sync

# Check throughput
# Expected: 15-25 items/second
# If <10 items/second: investigate bottlenecks
```

### Common Bottlenecks
1. **Slow search** → Not using Search API
2. **Slow fetch** → Not enough parallel workers
3. **Slow filter** → Database query needs index
4. **No progress** → Missing console.print statements
5. **Rate limiting** → Too many requests (unlikely with 20 workers)

## Code Review Checklist

Before committing network-related code, verify:

- [ ] Using GitHub Search API (not `repo.get_issues()` iteration)
- [ ] Parallel processing with ThreadPoolExecutor (max_workers=20)
- [ ] Progress feedback before/during/after each operation
- [ ] No silent periods >2 seconds
- [ ] Incremental sync (not fetching everything)
- [ ] Batch size 100-200 for optimal throughput
- [ ] Error handling with try/except
- [ ] Progress updates even on errors

## Anti-Patterns to Avoid

### ❌ Sequential Network Calls
```python
for item in items:
    result = api.fetch(item)  # BAD
```

### ❌ Lazy Iteration
```python
for issue in repo.get_issues():  # BAD - each iteration is a network call
    process(issue)
```

### ❌ No Progress Feedback
```python
# User sees nothing for 30 seconds - BAD
items = fetch_all_items()
```

### ❌ Fetching Everything Every Time
```python
all_data = fetch_all()  # BAD - wasteful
```

## Recommended Patterns

### ✅ Parallel Fetch with Progress
```python
console.print("[cyan]Fetching items...[/cyan]")

with Progress() as progress:
    task = progress.add_task("Fetching...", total=len(items))

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch, i): i for i in items}

        for future in as_completed(futures):
            result = future.result()
            progress.update(task, advance=1)
```

### ✅ Search API with Cutoff Date
```python
query = f"repo:{repo_name} is:issue"
if since:
    query += f" created:>={since.strftime('%Y-%m-%d')}"

console.print(f"[cyan]Searching...[/cyan]")
results = gh.search_issues(query)
console.print(f"[green]✓[/green] Found {len(results)} items")
```

### ✅ Incremental with Filtering
```python
existing = db.get_existing_numbers(repo)
new_only = [n for n in all_numbers if n not in existing]
console.print(f"[cyan]Fetching {len(new_only)} new items...[/cyan]")
```
