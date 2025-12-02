# Master Template Feature (`release_output_template` and `doc_output_template`)

## Overview

The master template system provides complete control over release notes structure through Jinja2 templates. As of v1.4, the tool supports **dual template output**:

- **`release_output_template`**: Template for GitHub release notes
- **`doc_output_template`**: Template for Docusaurus/documentation (wraps GitHub notes with frontmatter)

## What's New

### Before (Legacy Format)
- Fixed category-based structure
- Limited to: Title → Description → Categories with Entries
- No way to customize overall layout
- `description_template` only accepts version variable

### After (Master Template)
- **Full control** over entire release notes structure
- **Iterate** over categories, notes, migrations, descriptions
- **Custom sections** (e.g., migrations, contributors, breaking changes)
- **Entry sub-template** rendered via `render_entry()` function
- **Dual output** - separate templates for GitHub and Docusaurus (v1.4+)
- **Backward compatible** - legacy format still works when `release_output_template` is not set

## Key Features

### 1. GitHub Release Template (`release_output_template`)
```toml
[release_notes]
release_release_output_template = '''# {{ title }}

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}'''
```

### 2. Entry Sub-Template
```toml
[release_notes]
entry_template = '''- {{ title }}
  {% if url %}([#{{ pr_numbers[0] }}]({{ url }})){% endif %}
  {% if authors %}by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}'''
```

The `render_entry(note)` function renders the `entry_template` with the note's data.

### 3. Docusaurus Template (`doc_output_template`) - NEW in v1.4

The `doc_output_template` wraps the GitHub release notes with documentation-specific formatting:

```toml
[release_notes]
doc_release_output_template = '''---
id: release-{{version}}
title: {{title}}
---
<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
SPDX-License-Identifier: AGPL-3.0-only
-->
{{ render_release_notes() }}<br>'''

[output]
release_output_path = "docs/releases/{version}.md"
doc_output_path = "docs/docusaurus/docs/releases/release-{major}.{minor}/release-{major}.{minor}.{patch}.md"
```

**Key Points:**
- `render_release_notes()` embeds the GitHub release notes (from `release_output_template`)
- Has access to all variables: `version`, `title`, `categories`, `all_notes`, `render_entry()`
- Optional - only generates when both `doc_output_template` and `doc_output_path` are configured
- Generate command creates both files automatically

### 4. Available Variables

In `release_output_template`:
- `{{ version }}` - Version string (e.g., "1.2.3")
- `{{ title }}` - Rendered release title (from `title_template`)
- `{{ categories }}` - List of category dicts: `[{name: str, notes: [...]}, ...]`
- `{{ all_notes }}` - Flat list of all note dicts (across all categories)
- `{{ render_entry(note) }}` - Function to render a note using `entry_template`

In `doc_output_template` (additional variable):
- `{{ render_release_notes() }}` - Function to render the GitHub release notes (from `release_output_template`)
- Plus all variables from `release_output_template` above

Each note dict contains:
- `title` - Note title
- `url` - PR/ticket URL
- `pr_numbers` - List of PR numbers
- `commit_shas` - List of commit SHAs
- `labels` - List of label strings
- `ticket_key` - Ticket identifier
- `category` - Category name
- `description` - Processed description (may be None)
- `migration_notes` - Processed migration notes (may be None)
- `authors` - List of author dicts with all fields (name, username, email, company, etc.)

### 5. HTML-like Whitespace Processing

Both `entry_template`, `release_output_template`, and `doc_output_template` use HTML-like whitespace behavior:
- **Multiple spaces collapse** to single space
- **Newlines are ignored** unless using `<br>` or `<br/>`
- **Leading/trailing whitespace** stripped from lines

This allows readable multi-line templates with clean output.

## Use Cases

### 1. Separate Migrations Section
```toml
release_output_template = '''# {{ title }}

## Changes
{% for category in categories %}
### {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}

## Migration Guide
{% for note in all_notes %}
{% if note.migration_notes %}
### {{ note.title }}
{{ note.migration_notes }}
{% endif %}
{% endfor %}'''
```

### 2. Flat List (No Categories)
```toml
release_output_template = '''# {{ title }}

{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}'''
```

### 3. Full Descriptions as Sections
```toml
release_output_template = '''# {{ title }}

{% for note in all_notes %}
## {{ note.title }}
{% if note.description %}
{{ note.description }}
{% endif %}
{% if note.migration_notes %}
**Migration:** {{ note.migration_notes }}
{% endif %}
{% endfor %}'''
```

### 4. Contributors Section
```toml
release_output_template = '''# {{ title }}

## Changes
{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}

## Contributors
{% set all_authors = [] %}
{% for note in all_notes %}
  {% for author in note.authors %}
    {% if author not in all_authors %}
      {% set _ = all_authors.append(author) %}
    {% endif %}
  {% endfor %}
{% endfor %}
{% for author in all_authors %}
- {{ author.mention }}{% if author.company %} ({{ author.company }}){% endif %}
{% endfor %}'''
```

## Implementation Details

### Architecture

1. **Config Model** (`config.py`):
   - `release_output_template: Optional[str]` - GitHub release notes template
   - `doc_output_template: Optional[str]` - Docusaurus template (v1.4+)
   - `release_output_path: str` - Path for GitHub release notes
   - `doc_output_path: Optional[str]` - Path for Docusaurus output (v1.4+)
   - Maintains backward compatibility (None = use legacy format)

2. **Policy Class** (`policies.py`):
   - `format_markdown()` - Entry point, returns tuple or single string
   - `_format_with_master_template()` - Renders `release_output_template`
   - `_format_with_doc_template()` - Renders `doc_output_template` (v1.4+)
   - `_format_with_legacy_layout()` - Original category-based rendering
   - `_prepare_note_for_template()` - Processes notes (media, authors)
   - `_process_html_like_whitespace()` - HTML-like whitespace processing

3. **Template Rendering**:
   - Creates `render_entry(note_dict)` function closure
   - Passes to master template as callable
   - Processes output with HTML-like whitespace rules

### Data Flow

```
grouped_notes → _format_with_master_template()
    ↓
Prepare categories_data & all_notes_data
    ↓
Create render_entry() closure
    ↓
Render master template with:
    - version, title
    - categories, all_notes
    - render_entry function
    ↓
Process HTML-like whitespace
    ↓
Return formatted markdown
```

## Testing

Comprehensive test suite in `tests/test_output_template.py`:
- ✅ Category-based layout
- ✅ Flat list layout
- ✅ Migrations section layout
- ✅ Legacy format compatibility
- ✅ render_entry() with all fields
- ✅ HTML whitespace processing

All 56 tests pass (50 original + 6 new).

## Examples

See:
- `example_output_template.toml` - Migrations + contributors layout
- `example_flat_list.toml` - Simple flat list
- `example_detailed_descriptions.toml` - Full descriptions as sections
- `OUTPUT_TEMPLATE_EXAMPLES.md` - Complete guide with examples

## Migration Guide

### From v1.3 to v1.4

**Automatic Migration**: The tool automatically migrates your configuration from v1.3 to v1.4:
- `output_template` → `release_output_template`
- `output_path` → `release_output_path`
- Adds placeholders for `doc_output_template` and `doc_output_path` (optional)

Your existing customizations are preserved!

### From Legacy Format to Master Template

If you have:
```toml
[release_notes]
title_template = "Release {{ version }}"
description_template = "Some description"
entry_template = "- {{ title }}"
```

To use master template, add:
```toml
[release_notes]
release_output_template = '''# {{ title }}

Some description

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}'''
```

The `description_template` is now deprecated in favor of including it directly in `release_output_template`.

### Adding Docusaurus Support (v1.4+)

To generate Docusaurus documentation alongside GitHub release notes:

```toml
[release_notes]
# Your existing release_output_template
doc_output_template = '''---
id: release-{{version}}
title: {{title}}
---
{{ render_release_notes() }}'''

[output]
release_output_path = "docs/releases/{version}.md"
doc_output_path = "docs/docusaurus/docs/releases/release-{major}.{minor}/release-{major}.{minor}.{patch}.md"
```

## Backward Compatibility

✅ **100% backward compatible**
- If `release_output_template` is not set (None), uses legacy format
- Existing v1.3 configs are automatically migrated to v1.4
- `description_template` still works in legacy mode
- `doc_output_template` is optional - GitHub-only output still works

## Benefits

1. ✨ **Flexibility** - Complete control over layout
2. 🔄 **Iteration** - Loop over migrations, descriptions, authors
3. 📦 **Custom Sections** - Add breaking changes, contributors, etc.
4. 🎨 **Clean Templates** - HTML-like whitespace for readable code
5. 🔌 **Extensible** - Easy to add new sections and features
6. 📝 **Dual Output** - Generate GitHub and Docusaurus files simultaneously (v1.4+)
7. ↩️ **Backward Compatible** - Existing configs work unchanged

## Future Enhancements

Possible future additions:
- Filters for grouping (e.g., by label, author)
- Helper functions for common operations
- Template includes/macros
- More template examples for different use cases
