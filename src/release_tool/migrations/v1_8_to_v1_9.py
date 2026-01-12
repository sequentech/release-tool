# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Migration from config version 1.8 to 1.9.

Changes in 1.9:
- Changed repository.code_repo (string) to repository.code_repos (list of RepoInfo)
- Changed repository.issue_repos (list of strings) to list of RepoInfo objects
- Removed pull.clone_code_repo field (always clone now)
- Removed pull.code_repo_path field (always uses .release_tool_cache/{repo_alias})
- Each repository now has a 'link' and 'alias' for template referencing

This migration:
- Converts code_repo string to code_repos list with auto-generated alias
- Converts issue_repos strings to list of RepoInfo with auto-generated aliases
- Removes pull.clone_code_repo field
- Removes pull.code_repo_path field
- Updates config_version to "1.9"
"""

from typing import Dict, Any
import tomlkit


def _extract_alias_from_repo(repo_link: str) -> str:
    """
    Extract a simple alias from a repository link.

    Examples:
        "sequentech/step" -> "step"
        "sequentech/release-tool" -> "release-tool"
        "owner/my-repo" -> "my-repo"

    Args:
        repo_link: Full repository name (owner/repo)

    Returns:
        Simple alias (repo name part)
    """
    return repo_link.split('/')[-1]


def migrate(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from version 1.8 to 1.9.

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
    doc['config_version'] = '1.9'

    # Migrate repository.code_repo to repository.code_repos
    if 'repository' in doc:
        if 'code_repo' in doc['repository']:
            old_code_repo = doc['repository']['code_repo']
            alias = _extract_alias_from_repo(old_code_repo)

            # Remove old field
            del doc['repository']['code_repo']

            # Create new code_repos array of tables
            code_repos_array = tomlkit.aot()
            repo_table = tomlkit.table()
            repo_table['link'] = old_code_repo
            repo_table['alias'] = alias
            code_repos_array.append(repo_table)
            doc['repository']['code_repos'] = code_repos_array

            print(f"  • Converted code_repo '{old_code_repo}' to code_repos with alias '{alias}'")

        # Migrate repository.issue_repos from list of strings to list of RepoInfo
        if 'issue_repos' in doc['repository']:
            old_issue_repos = doc['repository']['issue_repos']

            # Check if old_issue_repos is a non-empty list
            if old_issue_repos and len(old_issue_repos) > 0:
                # Remove old field
                del doc['repository']['issue_repos']

                # Create new issue_repos array of tables
                issue_repos_array = tomlkit.aot()
                for repo_link in old_issue_repos:
                    alias = _extract_alias_from_repo(repo_link)
                    repo_table = tomlkit.table()
                    repo_table['link'] = repo_link
                    repo_table['alias'] = alias
                    issue_repos_array.append(repo_table)

                doc['repository']['issue_repos'] = issue_repos_array
                print(f"  • Converted {len(old_issue_repos)} issue_repos to new format with aliases")
            else:
                # If issue_repos was empty, just delete it (empty list is default)
                del doc['repository']['issue_repos']
                print("  • Removed empty issue_repos (will default to code_repos)")

    # Remove pull.clone_code_repo if it exists
    if 'pull' in doc and 'clone_code_repo' in doc['pull']:
        del doc['pull']['clone_code_repo']
        print("  • Removed pull.clone_code_repo (code repos are now always cloned)")

    # Remove pull.code_repo_path if it exists
    if 'pull' in doc and 'code_repo_path' in doc['pull']:
        del doc['pull']['code_repo_path']
        print("  • Removed pull.code_repo_path (path always uses .release_tool_cache/{repo_alias})")

    return doc
