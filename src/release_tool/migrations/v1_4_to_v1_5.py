# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.4 to 1.5.

Changes in 1.5:
- Renamed all "issue" terminology to "issue" throughout config
- issue_repos → issue_repos
- issue_policy → issue_policy
- no_issue_action → no_issue_action
- unclosed_issue_action → unclosed_issue_action
- partial_issue_action → partial_issue_action
- issue_templates → issue_templates
- Pattern named group: (?P<issue>) → (?P<issue>)
- Category label prefixes: issue: → issue:
- Database table: issues → issues (handled by Database.connect() migration)

This migration:
- Renames all issue-related config keys to issue equivalents
- Updates regex patterns to use (?P<issue>) instead of (?P<issue>)
- Updates label prefixes from issue: to issue:
- Updates config_version to "1.5"

Note: Database table rename is handled automatically by Database class
"""

from typing import Dict, Any
import tomlkit
import re


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.4 to 1.5.

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
    doc['config_version'] = '1.5'

    # Migrate repository section
    if 'repository' in doc:
        # Rename issue_repos → issue_repos
        if 'issue_repos' in doc['repository']:
            issue_repos_value = doc['repository']['issue_repos']
            del doc['repository']['issue_repos']
            doc['repository']['issue_repos'] = issue_repos_value

    # Migrate issue_policy → issue_policy section
    if 'issue_policy' in doc:
        policy_section = doc['issue_policy']
        del doc['issue_policy']

        # Rename action fields within the policy
        if isinstance(policy_section, dict):
            if 'no_issue_action' in policy_section:
                policy_section['no_issue_action'] = policy_section.pop('no_issue_action')
            if 'unclosed_issue_action' in policy_section:
                policy_section['unclosed_issue_action'] = policy_section.pop('unclosed_issue_action')
            if 'partial_issue_action' in policy_section:
                policy_section['partial_issue_action'] = policy_section.pop('partial_issue_action')

            # Update patterns - replace (?P<issue>) with (?P<issue>) in regex patterns
            if 'patterns' in policy_section and isinstance(policy_section['patterns'], list):
                for pattern_entry in policy_section['patterns']:
                    if isinstance(pattern_entry, dict) and 'pattern' in pattern_entry:
                        old_pattern = pattern_entry['pattern']
                        # Replace named group from issue to issue
                        new_pattern = old_pattern.replace('(?P<issue>', '(?P<issue>')
                        pattern_entry['pattern'] = new_pattern

        doc['issue_policy'] = policy_section

    # Migrate release_notes section - update category label prefixes
    if 'release_notes' in doc and 'categories' in doc['release_notes']:
        categories = doc['release_notes']['categories']
        if isinstance(categories, list):
            for category in categories:
                if isinstance(category, dict) and 'labels' in category:
                    labels = category['labels']
                    if isinstance(labels, list):
                        # Update issue: prefix to issue: prefix
                        updated_labels = []
                        for label in labels:
                            if isinstance(label, str) and label.startswith('issue:'):
                                updated_labels.append('issue:' + label[7:])  # Remove 'issue:' and add 'issue:'
                            else:
                                updated_labels.append(label)
                        category['labels'] = updated_labels

    # Migrate output section - rename issue_templates → issue_templates
    if 'output' in doc:
        if 'issue_templates' in doc['output']:
            issue_templates_value = doc['output']['issue_templates']
            del doc['output']['issue_templates']
            doc['output']['issue_templates'] = issue_templates_value

    return doc
