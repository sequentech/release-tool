# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.7 to 1.8.

Changes in 1.8:
- Removed [github].token config field for security
- GitHub token must now be provided via GITHUB_TOKEN environment variable
- Config.github.token property reads from environment variable

This migration:
- Removes github.token from config (if present)
- Updates config_version to "1.8"
"""

from typing import Dict, Any
import tomlkit


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.7 to 1.8.

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
    doc['config_version'] = '1.8'

    # Remove github.token if it exists (security improvement)
    if 'github' in doc and 'token' in doc['github']:
        # Don't print the token value for security
        del doc['github']['token']
        print("  • Removed github.token from config (security: tokens must use GITHUB_TOKEN env var)")
        print("  • Please set GITHUB_TOKEN environment variable before running commands")

    return doc
