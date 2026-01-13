# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.9 to 1.10.

Changes in 1.10:
- BREAKING: Replaced {{code_repo.primary.*}} with {{code_repo.current.*}}
- code_repo.current is context-aware (set during repo iteration loops)
- code_repo.current raises error when used outside of repo context
- Added code_repo_list and issue_repo_list for template iteration
- Fixed bug where code_repo dict was overwritten with string

This migration:
- Updates all template strings: {{code_repo.primary.*}} -> {{code_repo.current.*}}
- Updates config_version to "1.10"
"""

from typing import Dict, Any
import tomlkit
import re


def _replace_primary_with_current(value: str) -> str:
    """
    Replace all occurrences of code_repo.primary with code_repo.current in a string.

    Args:
        value: Template string that may contain code_repo.primary references

    Returns:
        Updated string with code_repo.current references
    """
    # Use regex to handle different forms:
    # {{code_repo.primary.slug}}, {{code_repo.primary.link}}, etc.
    return re.sub(r'\bcode_repo\.primary\b', 'code_repo.current', value)


def _migrate_value(value: Any) -> Any:
    """
    Recursively migrate a config value, updating template strings.

    Args:
        value: Any config value (string, dict, list, etc.)

    Returns:
        Migrated value
    """
    if isinstance(value, str):
        if 'code_repo.primary' in value:
            return _replace_primary_with_current(value)
        return value
    elif isinstance(value, dict):
        return {k: _migrate_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_migrate_value(item) for item in value]
    else:
        return value


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.9 to 1.10.

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
    doc['config_version'] = '1.10'

    # Track what we changed for reporting
    changes_made = []

    # Migrate output.draft_output_path
    if 'output' in doc and 'draft_output_path' in doc['output']:
        old_value = doc['output']['draft_output_path']
        if 'code_repo.primary' in old_value:
            doc['output']['draft_output_path'] = _replace_primary_with_current(old_value)
            changes_made.append('output.draft_output_path')

    # Migrate output.pr_templates
    if 'output' in doc and 'pr_templates' in doc['output']:
        pr_templates = doc['output']['pr_templates']
        for key in ['branch_template', 'title_template', 'body_template']:
            if key in pr_templates:
                old_value = pr_templates[key]
                if isinstance(old_value, str) and 'code_repo.primary' in old_value:
                    pr_templates[key] = _replace_primary_with_current(old_value)
                    changes_made.append(f'output.pr_templates.{key}')

    # Migrate output.issue_templates
    if 'output' in doc and 'issue_templates' in doc['output']:
        issue_templates = doc['output']['issue_templates']
        for key in ['title_template', 'body_template', 'milestone']:
            if key in issue_templates:
                old_value = issue_templates[key]
                if isinstance(old_value, str) and 'code_repo.primary' in old_value:
                    issue_templates[key] = _replace_primary_with_current(old_value)
                    changes_made.append(f'output.issue_templates.{key}')

    # Migrate output.pr_code.<alias>.templates[].output_path and output_template
    if 'output' in doc and 'pr_code' in doc['output']:
        pr_code = doc['output']['pr_code']
        for alias, alias_config in pr_code.items():
            if isinstance(alias_config, dict) and 'templates' in alias_config:
                for idx, template in enumerate(alias_config['templates']):
                    for key in ['output_path', 'output_template']:
                        if key in template:
                            old_value = template[key]
                            if isinstance(old_value, str) and 'code_repo.primary' in old_value:
                                template[key] = _replace_primary_with_current(old_value)
                                changes_made.append(f'output.pr_code.{alias}.templates[{idx}].{key}')

    # Migrate release_notes templates
    if 'release_notes' in doc:
        rn = doc['release_notes']
        for key in ['release_output_template', 'entry_template', 'title_template']:
            if key in rn:
                old_value = rn[key]
                if isinstance(old_value, str) and 'code_repo.primary' in old_value:
                    rn[key] = _replace_primary_with_current(old_value)
                    changes_made.append(f'release_notes.{key}')

    # Report changes
    if changes_made:
        print(f"  • Updated {len(changes_made)} template(s) from code_repo.primary to code_repo.current:")
        for change in changes_made:
            print(f"    - {change}")
    else:
        print("  • No code_repo.primary references found to update")

    return doc
