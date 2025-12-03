# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.3 to 1.4.

Changes in 1.4:
- Renamed output_template to release_output_template (for GitHub release notes)
- Added doc_output_template (for Docusaurus/documentation release notes)
- Renamed output_path to release_output_path (for GitHub release notes)
- Added doc_output_path (for Docusaurus output)
- Doc template can use render_release_notes() to wrap GitHub template

This migration:
- Renames output_template → release_output_template (preserves customizations)
- Renames output_path → release_output_path (preserves user paths)
- Adds doc_output_template = None (optional, users can configure later)
- Adds doc_output_path = None (optional, users can configure later)
- Updates config_version to "1.4"
"""

from typing import Dict, Any
import tomlkit


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.3 to 1.4.

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
    doc['config_version'] = '1.4'

    # Migrate release_notes section
    if 'release_notes' in doc:
        # Rename output_template → release_output_template
        if 'output_template' in doc['release_notes']:
            output_template_value = doc['release_notes']['output_template']
            del doc['release_notes']['output_template']
            doc['release_notes']['release_output_template'] = output_template_value

        # Add doc_output_template if not present
        if 'doc_output_template' not in doc['release_notes']:
            # Add a comment explaining the new field
            doc['release_notes'].add(tomlkit.comment(
                "doc_output_template: Optional Jinja2 template for Docusaurus/documentation output"
            ))
            doc['release_notes'].add(tomlkit.comment(
                "Example: '---\\nid: release-{{version}}\\ntitle: {{title}}\\n---\\n{{ render_release_notes() }}'"
            ))
            # Note: tomlkit doesn't support None directly in some versions, so we comment it out
            # Users can uncomment and configure when needed

    # Migrate output section
    if 'output' in doc:
        # Rename output_path → release_output_path
        if 'output_path' in doc['output']:
            output_path_value = doc['output']['output_path']
            del doc['output']['output_path']
            doc['output']['release_output_path'] = output_path_value

        # Add doc_output_path if not present
        if 'doc_output_path' not in doc['output']:
            # Add a comment explaining the new field
            doc['output'].add(tomlkit.comment(
                "doc_output_path: Optional path template for Docusaurus/documentation output"
            ))
            doc['output'].add(tomlkit.comment(
                "Example: 'docs/docusaurus/docs/releases/release-{major}.{minor}/release-{major}.{minor}.{patch}.md'"
            ))
            # Note: tomlkit doesn't support None directly in some versions, so we comment it out

    return doc
