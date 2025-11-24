# Output Template Examples

This document showcases different ways to use the `output_template` feature to customize your release notes layout.

## What is `output_template`?

The `output_template` is a **master Jinja2 template** that gives you complete control over the structure and layout of your release notes. When set, it replaces the default category-based layout.

### Key Concepts

1. **Master Template**: Controls the entire release notes structure
2. **Entry Template**: Sub-template for individual changes (used via `render_entry()`)
3. **Variables Available**:
   - `{{ version }}` - Version string (e.g., "1.2.3")
   - `{{ title }}` - Rendered release title
   - `{{ categories }}` - List of category dicts with 'name' and 'notes'
   - `{{ all_notes }}` - Flat list of all notes (across categories)
   - `{{ render_entry(note) }}` - Function to render individual entries

4. **Note Fields**: Each note dict contains:
   - `title`, `url`, `pr_numbers`, `commit_shas`, `labels`, `ticket_key`, `category`
   - `description`, `migration_notes` (may be None)
   - `authors` (list of author dicts with name, username, email, etc.)

## Example Configurations

### 1. Default Category-Based Layout (example_output_template.toml)

**Use Case**: Traditional changelog with categories and a dedicated migrations section

**Features**:
- Changes grouped by category (Features, Bug Fixes, etc.)
- Separate "Migration Guide" section for all migration notes
- Contributors list at the bottom

**Config**: `example_output_template.toml`

**Output Structure**:
```markdown
# Release 1.2.3

## What's Changed
### Features
- Add new feature ([#123](url)) by @alice
- Improve performance ([#124](url)) by @bob

### Bug Fixes
- Fix critical bug ([#125](url)) by @alice

## Migration Guide
### Fix critical bug
Update your config to use new format.
See PR #125 for details.

## Contributors
- @alice (Acme Corp)
- @bob
```

---

### 2. Flat List Layout (example_flat_list.toml)

**Use Case**: Simple chronological list without category grouping

**Features**:
- No category headers
- All changes in one flat list
- Rich entry template with inline descriptions

**Config**: `example_flat_list.toml`

**Output Structure**:
```markdown
# Release 1.2.3

All changes in this release:

- **Add new feature**
  Detailed description here
  [#123](url) by @alice `feature`

- **Fix critical bug**
  [#124](url) by @bob `bug` `urgent`
```

---

### 3. Detailed Descriptions Layout (example_detailed_descriptions.toml)

**Use Case**: Technical release notes with full ticket details

**Features**:
- Each ticket gets its own section (##)
- Full descriptions displayed
- Metadata block (category, PR, labels, authors)
- Inline migration notes
- Summary at the end

**Config**: `example_detailed_descriptions.toml`

**Output Structure**:
```markdown
# Release 1.2.3

## Add new feature

This feature allows users to do X, Y, and Z.
It improves performance by 50%.

**Details:**
- Category: Features
- Pull Request: [#123](url)
- Labels: `feature`, `enhancement`
- Authors: @alice, @bob

**Migration Notes:**
Run `npm run migrate` after upgrading.

---

## Fix critical bug

Fixed an issue where...

**Details:**
- Category: Bug Fixes
- Pull Request: [#124](url)
- Labels: `bug`
- Authors: @alice

---

## Summary

This release includes 2 changes across the following categories:
- **Features**: 1 change(s)
- **Bug Fixes**: 1 change(s)
```

---

## Creating Your Own Template

### Step 1: Choose Your Layout

Decide how you want to structure your release notes:
- **Category-based** (default): Group by Features, Bug Fixes, etc.
- **Flat list**: Simple chronological order
- **Detailed**: Each change as a full section
- **Custom**: Mix and match!

### Step 2: Define Entry Template

The `entry_template` defines how individual changes appear:

```toml
# Minimal
entry_template = "- {{ title }}"

# With PR link and authors
entry_template = '''- {{ title }}
  {% if url %}([#{{ pr_numbers[0] }}]({{ url }})){% endif %}
  {% if authors %}by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}'''
```

### Step 3: Create Output Template

Use the master template to control overall structure:

```toml
# Iterate over categories
output_template = '''# {{ title }}

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}'''

# OR iterate over all notes (flat)
output_template = '''# {{ title }}

{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}'''
```

### Step 4: Add Custom Sections

You can add any custom sections you want:

```toml
output_template = '''# {{ title }}

## Changes
{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}

## Breaking Changes
{% for note in all_notes %}
{% if "breaking" in note.labels %}
- {{ note.title }}: {{ note.migration_notes }}
{% endif %}
{% endfor %}

## Contributors
{% set all_authors = [] %}
{% for note in all_notes %}
  {% for author in note.authors %}
    {% if author.username not in (all_authors | map(attribute='username') | list) %}
      {% set _ = all_authors.append(author) %}
    {% endif %}
  {% endfor %}
{% endfor %}
{% for author in all_authors %}
- [{{ author.mention }}]({{ author.profile_url }})
{% endfor %}'''
```

## Tips & Tricks

### HTML-like Whitespace Behavior

Templates use HTML-like whitespace processing:
- Multiple spaces collapse to single space
- Newlines are ignored (use `<br>` or `<br/>` for explicit line breaks)
- Leading/trailing whitespace is stripped from lines

```toml
# These are equivalent:
entry_template = "- {{ title }} by {{ authors[0].mention }}"

entry_template = '''- {{ title }}
  by {{ authors[0].mention }}'''
```

### Accessing Author Fields

Each author dict has many fields:
- `{{ author.mention }}` - Smart @mention (username or name)
- `{{ author.username }}` - GitHub username
- `{{ author.name }}` - Git author name
- `{{ author.email }}` - Email address
- `{{ author.company }}` - Company name
- `{{ author.avatar_url }}` - Profile picture URL
- `{{ author.profile_url }}` - GitHub profile URL

### Conditional Sections

Show sections only when they have content:

```toml
output_template = '''# {{ title }}

## Changes
{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}

{% if all_notes | selectattr('migration_notes') | list | length > 0 %}
## Migrations
{% for note in all_notes %}
{% if note.migration_notes %}
- {{ note.title }}: {{ note.migration_notes }}
{% endif %}
{% endfor %}
{% endif %}'''
```

### Custom Filtering

Use Jinja2 filters to manipulate data:

```toml
# Count changes by category
{% for category in categories %}
- {{ category.name }}: {{ category.notes | length }} changes
{% endfor %}

# Show only certain labels
{% for note in all_notes %}
{% if "feature" in note.labels %}
- NEW: {{ note.title }}
{% endif %}
{% endfor %}
```

## Migration from Legacy Format

If you're not using `output_template`, the tool uses the legacy format with:
- `title_template` - For the main title
- `description_template` - For optional description (deprecated)
- `entry_template` - For each entry
- Hardcoded category-based structure

To migrate to `output_template`:

1. Start with the default template:
```toml
output_template = '''# {{ title }}

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}'''
```

2. Add your custom sections (migrations, contributors, etc.)

3. Customize as needed!

## Testing Your Template

Use the CLI to preview your release notes:

```bash
# Generate release notes without writing to file
poetry run release-tool generate 1.2.3

# Write to file
poetry run release-tool generate 1.2.3 --output
```

Check the output and adjust your template until it looks perfect!
