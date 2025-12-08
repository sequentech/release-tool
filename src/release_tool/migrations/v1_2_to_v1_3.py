# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.2 to 1.3.

Changes in 1.3:
- Fixed issue key format: issues now stored without "#" prefix in database
- Updated db.get_issue_by_key() and db.query_issues() to normalize keys
- Breaking change: requires database migration to strip "#" from existing issue keys

This migration:
- Updates config_version to "1.3"
- No config field changes required
- Note: Database will be automatically migrated on next sync, or run with --force-db-migration
"""

from typing import Dict, Any
import tomlkit


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.2 to 1.3.

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
    doc['config_version'] = '1.3'

    # No other config changes needed for this version
    # The main change is in database storage format (handled separately)

    return doc
