# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.6 to 1.7.

Changes in 1.7:
- Moved documentation_release_version_policy from [release_notes] to each [[pr_code.templates]] entry
- Renamed documentation_release_version_policy to release_version_policy

This migration:
- Moves release_notes.documentation_release_version_policy to pr_code.templates[*].release_version_policy
- Removes release_notes.documentation_release_version_policy
- Updates config_version to "1.7"
"""

from typing import Dict, Any
import tomlkit


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.6 to 1.7.

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
    doc['config_version'] = '1.7'

    # Get documentation_release_version_policy from release_notes (if it exists)
    doc_release_version_policy = None
    if 'release_notes' in doc and 'documentation_release_version_policy' in doc['release_notes']:
        doc_release_version_policy = doc['release_notes']['documentation_release_version_policy']
        del doc['release_notes']['documentation_release_version_policy']
        print(f"  • Removed release_notes.documentation_release_version_policy (value: {doc_release_version_policy})")

    # Add release_version_policy to each pr_code.templates entry
    if 'pr_code' in doc and 'templates' in doc['pr_code'] and doc['pr_code']['templates']:
        # If we have a policy value from release_notes, use it; otherwise use default
        policy_value = doc_release_version_policy if doc_release_version_policy else "final-only"

        for i, template in enumerate(doc['pr_code']['templates']):
            if 'release_version_policy' not in template:
                template['release_version_policy'] = policy_value
                print(f"  • Added pr_code.templates[{i}].release_version_policy = '{policy_value}'")
    elif doc_release_version_policy:
        # We have a policy but no templates - just note it was removed
        print(f"  • Note: No pr_code.templates found, policy value '{doc_release_version_policy}' removed")

    return doc
