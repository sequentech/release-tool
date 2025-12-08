# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.1 to 1.2.

Changes in 1.2:
- Added issue_policy.partial_issue_action (ignore/warn/error)
- Handles issues extracted but not found in database or found in different repo
- Provides diagnostics for partial matches with potential reasons

This migration:
- Adds partial_issue_action = "warn" to [issue_policy]
- Updates config_version to "1.2"
"""

from typing import Dict, Any
import tomlkit


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.1 to 1.2.

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
    doc['config_version'] = '1.2'

    # Add partial_issue_action to issue_policy if not already present
    if 'issue_policy' not in doc:
        doc['issue_policy'] = {}

    if 'partial_issue_action' not in doc['issue_policy']:
        doc['issue_policy']['partial_issue_action'] = 'warn'

    return doc
