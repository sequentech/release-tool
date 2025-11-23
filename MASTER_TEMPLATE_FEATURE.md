# Master Template Feature (`output_template`)

## Overview

The `output_template` feature provides complete control over release notes structure through a master Jinja2 template system.

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
- **Backward compatible** - legacy format still works when `output_template` is not set

## Key Features

### 1. Master Template Control
```toml
[release_notes]
output_template = '''# {{ title }}

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

### 3. Available Variables

In `output_template`:
- `{{ version }}` - Version string (e.g., "1.2.3")
- `{{ title }}` - Rendered release title (from `title_template`)
- `{{ categories }}` - List of category dicts: `[{name: str, notes: [...]}, ...]`
- `{{ all_notes }}` - Flat list of all note dicts (across all categories)
- `{{ render_entry(note) }}` - Function to render a note using `entry_template`

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

### 4. HTML-like Whitespace Processing

Both `entry_template` and `output_template` use HTML-like whitespace behavior:
- **Multiple spaces collapse** to single space
- **Newlines are ignored** unless using `<br>` or `<br/>`
- **Leading/trailing whitespace** stripped from lines

This allows readable multi-line templates with clean output.

## Use Cases

### 1. Separate Migrations Section
```toml
output_template = '''# {{ title }}

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
output_template = '''# {{ title }}

{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}'''
```

### 3. Full Descriptions as Sections
```toml
output_template = '''# {{ title }}

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
output_template = '''# {{ title }}

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
   - Added `output_template: Optional[str]` field
   - Maintains backward compatibility (None = use legacy format)

2. **Policy Class** (`policies.py`):
   - `format_markdown()` - Entry point, routes to master or legacy format
   - `_format_with_master_template()` - New master template rendering
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

### From Legacy Format

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
output_template = '''# {{ title }}

Some description

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}'''
```

The `description_template` is now deprecated in favor of including it directly in `output_template`.

## Backward Compatibility

✅ **100% backward compatible**
- If `output_template` is not set (None), uses legacy format
- Existing configs continue to work without changes
- `description_template` still works in legacy mode

## Benefits

1. ✨ **Flexibility** - Complete control over layout
2. 🔄 **Iteration** - Loop over migrations, descriptions, authors
3. 📦 **Custom Sections** - Add breaking changes, contributors, etc.
4. 🎨 **Clean Templates** - HTML-like whitespace for readable code
5. 🔌 **Extensible** - Easy to add new sections and features
6. ↩️ **Backward Compatible** - Existing configs work unchanged

## Future Enhancements

Possible future additions:
- Filters for grouping (e.g., by label, author)
- Helper functions for common operations
- Template includes/macros
- More template examples for different use cases
