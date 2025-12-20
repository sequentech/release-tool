# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.5 to 1.6.

Changes in 1.6:
- Removed release_output_path from [output]
- Removed release_output_template from [release_notes]
- Migrated doc_output_template and doc_output_path to [[pr_code.templates]] array
- Added [pr_code] section with templates array for flexible code generation

This migration:
- Removes output.release_output_path (no longer needed)
- Removes release_notes.release_output_template (moved to DEFAULT_RELEASE_NOTES_TEMPLATE in code)
- Converts doc_output_template and doc_output_path to pr_code.templates array
- Creates [[pr_code.templates]] array with one entry if doc_output_template exists
- Updates config_version to "1.6"
"""

from typing import Dict, Any
import tomlkit


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.5 to 1.6.

    Args:
        config_dict: Config dictionary/document loaded from TOML

    Returns:
        Upgraded config dictionary/document
    """
    # If it's already a tomlkit document, modify in place to preserve comments
    # Otherwise, create a new document
    if hasattr(config_dict, 'add'):  # tomlkit document has 'add' method
        doc = config_dict
    else:
        doc = tomlkit.document()
        for key, value in config_dict.items():
            doc[key] = value

    # Update config_version
    doc['config_version'] = '1.6'

    # Remove output.release_output_path if it exists
    if 'output' in doc and 'release_output_path' in doc['output']:
        del doc['output']['release_output_path']
        print("  • Removed output.release_output_path")

    # Remove release_notes.release_output_template if it exists
    if 'release_notes' in doc and 'release_output_template' in doc['release_notes']:
        del doc['release_notes']['release_output_template']
        print("  • Removed release_notes.release_output_template (now DEFAULT_RELEASE_NOTES_TEMPLATE in code)")

    # Migrate doc_output_template and doc_output_path to pr_code.templates
    doc_output_template = None
    doc_output_path = None

    if 'release_notes' in doc and 'doc_output_template' in doc['release_notes']:
        doc_output_template = doc['release_notes']['doc_output_template']
        del doc['release_notes']['doc_output_template']
        print("  • Migrated release_notes.doc_output_template → pr_code.templates[0].output_template")

    if 'output' in doc and 'doc_output_path' in doc['output']:
        doc_output_path = doc['output']['doc_output_path']
        del doc['output']['doc_output_path']
        print("  • Migrated output.doc_output_path → pr_code.templates[0].output_path")

    # Create pr_code section with templates if we have doc_output_template
    if doc_output_template or doc_output_path:
        if 'pr_code' not in doc:
            doc['pr_code'] = tomlkit.table()

        # Create templates array
        if 'templates' not in doc['pr_code']:
            doc['pr_code']['templates'] = tomlkit.array()

        # Add the migrated template
        template_entry = tomlkit.table()

        if doc_output_template:
            template_entry['output_template'] = doc_output_template
        else:
            # Provide a default template if only path was configured
            template_entry['output_template'] = '''---
id: release-{{version}}
title: {{title}}
---
<!--
SPDX-FileCopyrightText: {{year}} Sequent Tech Inc <legal@sequentech.io>
SPDX-License-Identifier: AGPL-3.0-only
-->
# Release {{version}}

{{ render_release_notes() }}
'''

        if doc_output_path:
            template_entry['output_path'] = doc_output_path
        else:
            # Provide a default path if only template was configured
            template_entry['output_path'] = "docs/releases/{{version}}.md"

        doc['pr_code']['templates'].append(template_entry)
        print("  • Created pr_code.templates with 1 template entry")
    else:
        # No doc_output_template, create empty pr_code.templates array
        if 'pr_code' not in doc:
            doc['pr_code'] = tomlkit.table()
        if 'templates' not in doc['pr_code']:
            doc['pr_code']['templates'] = tomlkit.array()
        print("  • Created empty pr_code.templates array")

    return doc
