<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Release Tool Architecture Guidelines

## Command Separation of Concerns

The release tool has a strict separation between online (GitHub API) and offline operations:

### ✅ `sync` command - GitHub Fetching (Online)
- **Purpose**: Fetch data from GitHub API and store in local database
- **Internet**: REQUIRED
- **Operations**:
  - Fetch ALL issues from issue repos (comprehensive initial sync)
  - Fetch pull requests from code repo
  - Clone/update git repository
  - Store everything in local SQLite database
- **Rules**:
  - ✅ CAN call GitHub API
  - ✅ CAN write to database
  - ✅ CAN clone/update git repos
  - ❌ MUST NOT generate release notes

### ✅ `generate` command - Release Note Generation (Offline)
- **Purpose**: Generate release notes from local database
- **Internet**: NOT REQUIRED (must work offline)
- **Operations**:
  - Read commits from git repository
  - Extract issue references from branches/PRs/commits
  - Query issues from LOCAL database only
  - Generate formatted release notes
- **Rules**:
  - ✅ CAN read from database
  - ✅ CAN read from local git repo
  - ✅ CAN write release notes to files
  - ❌ MUST NOT call GitHub API
  - ❌ MUST NOT fetch issues from GitHub
  - ⚠️ If issue not in DB: warn user to run `sync` first

### ✅ `publish` command - GitHub Publishing (Online)
- **Purpose**: Upload release notes to GitHub
- **Internet**: REQUIRED
- **Operations**:
  - Create GitHub releases
  - Post comments on PRs
  - Upload release assets
- **Rules**:
  - ✅ CAN call GitHub API
  - ✅ CAN read from database
  - ❌ MUST NOT fetch additional data from GitHub

### ✅ `issues` command - Database Query (Offline)
- **Purpose**: Query and explore issues in local database
- **Internet**: NOT REQUIRED (fully offline)
- **Operations**:
  - Search issues by key, repo, or fuzzy patterns
  - Support smart ISSUE_KEY formats (8624, #8624, meta#8624, meta#8624~, owner/repo#8624)
  - Export issue data to CSV
  - Debug partial issue matches
  - Explore synced data
- **Rules**:
  - ✅ CAN read from database
  - ✅ CAN display data in table or CSV format
  - ❌ MUST NOT call GitHub API
  - ⚠️ Only shows synced issues (remind user to sync first)

### Use Cases for issues:
- **Debugging partial matches**: Find why a issue wasn't matched during release note generation
- **Exploring issues**: See what issues are in the database
- **Data export**: Export issues to CSV for analysis
- **Number proximity**: Find issues with similar numbers (useful for tracking down typos)
- **Pattern matching**: Use starts-with, ends-with for flexible searching

## Database Design

### Issue Storage
- Issues are stored with their source `repo_id` (e.g., sequentech/meta)
- Code repos and issue repos have different repo_ids
- Use `db.get_issue_by_key(key)` to search across all repos
- Use `db.get_issue(repo_id, key)` only when repo is known

## Sync Strategy

### Initial Sync (First Time)
- Fetch ALL issues from issue repos (no cutoff date)
- Fetch ALL pull requests from code repo (no cutoff date)
- This ensures historical issues are available

### Incremental Sync (Subsequent Runs)
- Use `last_sync` timestamp as cutoff
- Only fetch items created/updated since last sync
- Much faster than initial sync

## Common Pitfalls

### ❌ DON'T: Add GitHub fetching to generate
```python
# BAD - This makes generate require internet
github_client = GitHubClient(config)
issue = github_client.fetch_issue_by_key(repo, key, repo_id)
```

### ✅ DO: Query from database only
```python
# GOOD - Works offline
issue = db.get_issue_by_key(change.issue_key)
if not issue:
    console.print("Issue not found. Run 'sync' first.")
```

### ❌ DON'T: Query with wrong repo_id
```python
# BAD - code_repo_id won't find issues from issue repos
issue = db.get_issue(code_repo_id, "8624")
```

### ✅ DO: Search across all repos
```python
# GOOD - Finds issue in any repo
issue = db.get_issue_by_key("8624")
```

## Testing Guidelines

- Generate command tests should NOT mock GitHub API
- Generate command tests MUST work with database only
- Sync command tests CAN mock GitHub API
- Publish command tests CAN mock GitHub API

## When Adding Features

Before adding any code to `generate` command:
1. Ask: "Does this require internet?"
2. If YES: Move it to `sync` or `publish`
3. If NO: Ensure it only reads from database/git

## User Workflow

1. **Setup**: `release-tool sync` (fetch all data from GitHub)
2. **Generate**: `release-tool generate 9.3.0-rc.7` (offline, uses cached data)
3. **Publish**: `release-tool publish 9.3.0-rc.7` (upload to GitHub)

Users should be able to:
- Run `generate` on airplane (offline)
- Run `generate` repeatedly without API rate limits
- Run `generate` on different machines after syncing once

## Config Versioning and Migrations

### Overview
The release tool uses semantic versioning for config files to handle breaking changes and new features gracefully.

### Current Version
- **Latest**: 1.2 (defined in `src/release_tool/migrations/manager.py`)
- Stored in config file as `config_version = "1.2"`

### Version History
- **1.0**: Initial config format
- **1.1**: Added template variables (issue_url, pr_url)
- **1.2**: Added partial_issue_action policy

### When to Bump Config Version

**ALWAYS bump config version when:**
- Adding new required fields
- Changing field meanings/behavior
- Changing default values that affect existing configs
- Adding new policy options

**NO bump needed when:**
- Adding optional fields with sensible defaults
- Adding documentation/comments
- Fixing bugs that don't change behavior
- Adding new sections that are entirely optional

### How to Bump Config Version

When adding a new config field or changing config structure:

1. **Update MigrationManager** (`src/release_tool/migrations/manager.py`):
   ```python
   CURRENT_VERSION = "1.3"  # Bump version
   ```

2. **Create Migration File** (`src/release_tool/migrations/vX_Y_to_vX_Z.py`):
   ```python
   """Migration from config version X.Y to X.Z.

   Changes in X.Z:
   - Added field_name to section_name
   - Changed behavior of existing_field
   """
   import tomlkit
   from typing import Dict, Any

   def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
       """Migrate config from X.Y to X.Z."""
       doc = tomlkit.document()

       # Preserve existing config
       for key, value in config_dict.items():
           doc[key] = value

       # Update version
       doc['config_version'] = 'X.Z'

       # Add new fields with defaults
       if 'section_name' not in doc:
           doc['section_name'] = {}
       if 'field_name' not in doc['section_name']:
           doc['section_name']['field_name'] = 'default_value'

       return doc
   ```

3. **Add Migration Description** (in `manager.py`):
   ```python
   descriptions = {
       # ... existing ...
       ("X.Y", "X.Z"): (
           "Version X.Z adds:\n"
           "  • New field_name in section_name\n"
           "  • Changed behavior description"
       ),
   }
   ```

4. **Update config_template.toml**:
   - Update version number at top
   - Add new fields with extensive comments
   - Document all options and examples

5. **Update Config Models** (`src/release_tool/config.py`):
   - Add new fields to Pydantic models
   - Set appropriate defaults
   - Add validation if needed

6. **Create Tests**:
   - Test migration function in `tests/test_migrations.py`
   - Test new config fields
   - Verify backwards compatibility

7. **Update Architecture Docs** (this file):
   - Add version to history
   - Document what changed

### Migration System

**Automatic Migration**:
- When user runs any command with old config
- Tool prompts: "Config is v1.1, upgrade to v1.2? [Y/n]"
- Auto-upgrades in `--auto` mode
- Preserves user's existing settings
- Saves upgraded config back to file

**Manual Migration**:
```bash
release-tool update-config  # Upgrades config to latest version
```

**Migration Chain**:
- Supports multi-step migrations (1.0 → 1.1 → 1.2)
- Each migration file handles one version jump
- Manager applies migrations in sequence

### Testing Migrations

**Requirements**:
- Every migration MUST have tests
- Test that migration adds expected fields
- Test that existing fields are preserved
- Test that defaults are sensible
- Test error handling for malformed configs

**Example Test**:
```python
def test_migration_1_1_to_1_2():
    """Test migration from v1.1 to v1.2."""
    from release_tool.migrations.v1_1_to_v1_2 import migrate

    old_config = {
        'config_version': '1.1',
        'repository': {'code_repo': 'test/repo'},
        'issue_policy': {}
    }

    new_config = migrate(old_config)

    assert new_config['config_version'] == '1.2'
    assert new_config['issue_policy']['partial_issue_action'] == 'warn'
    assert new_config['repository']['code_repo'] == 'test/repo'  # Preserved
```

### Common Migration Patterns

**Adding Field with Default**:
```python
if 'section' not in doc:
    doc['section'] = {}
if 'new_field' not in doc['section']:
    doc['section']['new_field'] = 'default'
```

**Adding Section**:
```python
if 'new_section' not in doc:
    doc['new_section'] = {
        'field1': 'value1',
        'field2': 'value2'
    }
```

**Renaming Field**:
```python
if 'old_name' in doc['section']:
    doc['section']['new_name'] = doc['section']['old_name']
    del doc['section']['old_name']
```

**Changing Default**:
```python
# Only change if user hasn't customized it
if doc['section'].get('field') == 'old_default':
    doc['section']['field'] = 'new_default'
```

### TOML Preservation

⚠️ **CRITICAL**: Use `tomlkit` for BOTH reading AND writing configs!

❌ **BAD** - Loses comments:
```python
import tomli
with open(path, 'rb') as f:
    data = tomli.load(f)  # Returns plain dict, NO comments!
```

✅ **GOOD** - Preserves comments:
```python
import tomlkit
with open(path, 'r', encoding='utf-8') as f:
    data = tomlkit.load(f)  # Preserves comments and formatting
```

**Rules**:
- Use `tomlkit` for reading configs (NOT `tomli`)
- Use text mode `'r'` (NOT binary `'rb'`)
- Use `tomlkit.load()` and `tomlkit.dumps()`
- Comments and formatting are preserved automatically
- Only modify what's necessary

### Error Handling

**Migration Fails**:
- Display clear error message
- Don't save partial config
- Suggest manual fix or file issue

**Malformed Config**:
- Validate before migration
- Provide helpful error messages
- Include line numbers if possible

## CLI Patterns

### Confirmation Prompts

ALL commands with user confirmations MUST respect both `--auto` and `-y/--assume-yes` flags.

**Flags**:
- `--auto`: Non-interactive mode (skip all prompts, use defaults) - for automation/CI
- `-y, --assume-yes`: Answer "yes" to confirmations - for interactive convenience

**Pattern**:
```python
@click.pass_context
def my_command(ctx, ...):
    # Get flags from context
    auto = ctx.obj.get('auto', False)
    assume_yes = ctx.obj.get('assume_yes', False)

    # Check before prompting
    if not (auto or assume_yes):
        if not click.confirm("Proceed?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # Continue with operation...
```

**Requirements**:
- ✅ ALL future commands with confirmations MUST implement this pattern
- ✅ Check BOTH flags: `if not (auto or assume_yes):`
- ✅ Always print cancellation message if user says no
- ⚠️ Never prompt if either flag is set

### Help Text Formatting

Use `\b` marker to preserve formatting in command docstrings:

```python
@cli.command()
def my_command():
    """\b
    This is my command.

    Examples:
      command --option1
      command --option2

    The \b prevents Click from rewrapping text.
    """
```

Without `\b`, Click will collapse all text into paragraphs and break formatting.

**Requirements**:
- ✅ ALL commands with examples or formatted lists MUST use `\b`
- ✅ Place `\b` on its own line right after the opening `"""`
- ✅ Maintain proper indentation in docstrings
- ⚠️ Test help output with `--help` to verify formatting
