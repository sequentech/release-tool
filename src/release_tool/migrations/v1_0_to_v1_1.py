"""Migration from config version 1.0 to 1.1.

Changes in 1.1:
- Added template variables: ticket_url, pr_url
- Improved output_template formatting (better spacing, blank lines)
- url field now smart: ticket_url if available, else pr_url
- Templates formatted as multiline literal strings for readability

This migration:
- Updates output_template to new format (if it's still the default)
- Converts templates to multiline format using '''...'''
- Adds config_version field set to "1.1"
"""

from typing import Dict, Any
import tomlkit

# Default v1.0 output_template (for comparison)
V1_0_DEFAULT_OUTPUT_TEMPLATE = (
    "# {{ title }}\n"
    "\n"
    "{% set breaking_with_desc = all_notes|selectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}\n"
    "{% if breaking_with_desc|length > 0 %}\n"
    "## 💥 Breaking Changes\n"
    "{% for note in breaking_with_desc %}\n"
    "### {{ note.title }}\n"
    "{{ note.description }}\n"
    "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
    "\n"
    "{% endfor %}\n"
    "{% endif %}\n"
    "{% set migration_notes = all_notes|selectattr('migration_notes')|list %}\n"
    "{% if migration_notes|length > 0 %}\n"
    "## 🔄 Migrations\n"
    "{% for note in migration_notes %}\n"
    "### {{ note.title }}\n"
    "{{ note.migration_notes }}\n"
    "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
    "\n"
    "{% endfor %}\n"
    "{% endif %}\n"
    "{% set non_breaking_with_desc = all_notes|rejectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}\n"
    "{% if non_breaking_with_desc|length > 0 %}\n"
    "## 📝 Highlights\n"
    "{% for note in non_breaking_with_desc %}\n"
    "### {{ note.title }}\n"
    "{{ note.description }}\n"
    "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
    "\n"
    "{% endfor %}\n"
    "{% endif %}\n"
    "## 📋 All Changes\n"
    "{% for category in categories %}\n"
    "### {{ category.name }}\n"
    "{% for note in category.notes %}\n"
    "{{ render_entry(note) }}\n"
    "{% endfor %}\n"
    "\n"
    "{% endfor %}"
)

# New v1.1 output_template (improved formatting) - as Python string
V1_1_DEFAULT_OUTPUT_TEMPLATE_STR = (
    "# {{ title }}\n"
    "\n"
    "{% set breaking_with_desc = all_notes|selectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}\n"
    "{% if breaking_with_desc|length > 0 %}\n"
    "## 💥 Breaking Changes\n"
    "\n"
    "{% for note in breaking_with_desc %}\n"
    "### {{ note.title }}\n"
    "\n"
    "{{ note.description }}\n"
    "\n"
    "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
    "\n"
    "{% endfor %}\n"
    "{% endif %}\n"
    "\n"
    "{% set migration_notes = all_notes|selectattr('migration_notes')|list %}\n"
    "{% if migration_notes|length > 0 %}\n"
    "## 🔄 Migrations\n"
    "\n"
    "{% for note in migration_notes %}\n"
    "### {{ note.title }}\n"
    "\n"
    "{{ note.migration_notes }}\n"
    "\n"
    "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
    "\n"
    "{% endfor %}\n"
    "{% endif %}\n"
    "\n"
    "{% set non_breaking_with_desc = all_notes|rejectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}\n"
    "{% if non_breaking_with_desc|length > 0 %}\n"
    "## 📝 Highlights\n"
    "\n"
    "{% for note in non_breaking_with_desc %}\n"
    "### {{ note.title }}\n"
    "\n"
    "{{ note.description }}\n"
    "\n"
    "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
    "\n"
    "{% endfor %}\n"
    "{% endif %}\n"
    "\n"
    "## 📋 All Changes\n"
    "\n"
    "{% for category in categories %}\n"
    "### {{ category.name }}\n"
    "\n"
    "{% for note in category.notes %}\n"
    "{{ render_entry(note) }}\n"
    "\n"
    "{% endfor %}\n"
    "{% endfor %}"
)

# Multiline literal string version (for TOML formatting)
V1_1_DEFAULT_OUTPUT_TEMPLATE = '''# {{ title }}

{% set breaking_with_desc = all_notes|selectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}
{% if breaking_with_desc|length > 0 %}
## 💥 Breaking Changes

{% for note in breaking_with_desc %}
### {{ note.title }}

{{ note.description }}

{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}

{% set migration_notes = all_notes|selectattr('migration_notes')|list %}
{% if migration_notes|length > 0 %}
## 🔄 Migrations

{% for note in migration_notes %}
### {{ note.title }}

{{ note.migration_notes }}

{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}

{% set non_breaking_with_desc = all_notes|rejectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}
{% if non_breaking_with_desc|length > 0 %}
## 📝 Highlights

{% for note in non_breaking_with_desc %}
### {{ note.title }}

{{ note.description }}

{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}

## 📋 All Changes

{% for category in categories %}
### {{ category.name }}

{% for note in category.notes %}
{{ render_entry(note) }}

{% endfor %}
{% endfor %}'''

# Default entry template as multiline
V1_1_DEFAULT_ENTRY_TEMPLATE = '''- {{ title }}
  {% if url %}{{ url }}{% endif %}
  {% if authors %}
  by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}
  {% endif %}'''


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.0 to 1.1.

    Args:
        config_dict: Config dictionary loaded from TOML

    Returns:
        Upgraded config dictionary (can be regular dict, tomlkit will format it)
    """
    # Parse the dict with tomlkit to preserve structure
    doc = tomlkit.document()

    # Copy all existing content
    for key, value in config_dict.items():
        doc[key] = value

    # Update config_version
    doc['config_version'] = '1.1'

    # Update output_template if it's still the default v1.0 template
    if 'release_notes' in doc:
        current_template = doc['release_notes'].get('output_template')
        current_entry = doc['release_notes'].get('entry_template')

        # Compare against both string formats (with \n and without)
        if current_template in [V1_0_DEFAULT_OUTPUT_TEMPLATE, V1_1_DEFAULT_OUTPUT_TEMPLATE_STR]:
            # Create a multiline literal string
            multiline_output = tomlkit.string(V1_1_DEFAULT_OUTPUT_TEMPLATE, literal=True, multiline=True)
            doc['release_notes']['output_template'] = multiline_output
        elif current_template and '\n' in current_template:
            # Convert any template with newlines to multiline format
            multiline_output = tomlkit.string(current_template, literal=True, multiline=True)
            doc['release_notes']['output_template'] = multiline_output

        # Also convert entry_template to multiline if it has newlines
        if current_entry and '\n' in current_entry:
            multiline_entry = tomlkit.string(current_entry, literal=True, multiline=True)
            doc['release_notes']['entry_template'] = multiline_entry
        elif not current_entry or current_entry == "- {{ title }}\n  {% if url %}{{ url }}{% endif %}\n  {% if authors %}\n  by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}\n  {% endif %}":
            # Set default multiline entry template
            multiline_entry = tomlkit.string(V1_1_DEFAULT_ENTRY_TEMPLATE, literal=True, multiline=True)
            doc['release_notes']['entry_template'] = multiline_entry

    return doc
