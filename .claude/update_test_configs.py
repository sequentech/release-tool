#!/usr/bin/env python3
"""Script to update test config dictionaries to new format (v1.9)."""

import re
from pathlib import Path

def extract_alias_from_repo(repo_link: str) -> str:
    """Extract alias from repo link (e.g., 'sequentech/step' -> 'step')."""
    return repo_link.split('/')[-1]

def replace_code_repo(content: str) -> str:
    """Replace code_repo with code_repos format."""
    # Pattern: "code_repo": "owner/repo"
    pattern = r'"code_repo":\s*"([^"]+)"'

    def replacer(match):
        repo_link = match.group(1)
        alias = extract_alias_from_repo(repo_link)
        return f'"code_repos": [{{"link": "{repo_link}", "alias": "{alias}"}}]'

    return re.sub(pattern, replacer, content)

def replace_issue_repos(content: str) -> str:
    """Replace issue_repos list of strings with list of RepoInfo."""
    # Pattern: "issue_repos": ["repo1", "repo2", ...]
    # This is tricky because the list can span multiple lines
    # Let's use a simpler approach - find each issue_repos and handle it

    pattern = r'"issue_repos":\s*\[((?:[^]]*?))\]'

    def replacer(match):
        inner = match.group(1).strip()
        if not inner:
            # Empty list
            return '"issue_repos": []'

        # Extract all quoted strings
        repos = re.findall(r'"([^"]+)"', inner)

        # Build RepoInfo objects
        repo_infos = []
        for repo_link in repos:
            alias = extract_alias_from_repo(repo_link)
            repo_infos.append(f'{{"link": "{repo_link}", "alias": "{alias}"}}')

        return f'"issue_repos": [{", ".join(repo_infos)}]'

    return re.sub(pattern, replacer, content, flags=re.DOTALL)

def remove_clone_code_repo(content: str) -> str:
    """Remove clone_code_repo field from config dicts."""
    # Pattern: "clone_code_repo": True/False with optional comma and whitespace
    pattern = r',?\s*"clone_code_repo":\s*(?:True|False)\s*,?'

    # Replace with empty string, but need to handle comma cleanup
    def replacer(match):
        text = match.group(0)
        # If there's a comma before and after, keep one
        if text.strip().startswith(',') and text.strip().endswith(','):
            return ','
        return ''

    return re.sub(pattern, replacer, content)

def update_file(file_path: Path):
    """Update a single file."""
    print(f"Updating {file_path}...")

    content = file_path.read_text()
    original_content = content

    # Apply transformations
    content = replace_code_repo(content)
    content = replace_issue_repos(content)
    content = remove_clone_code_repo(content)

    if content != original_content:
        file_path.write_text(content)
        print(f"  ✓ Updated {file_path.name}")
    else:
        print(f"  - No changes needed for {file_path.name}")

def main():
    """Main entry point."""
    test_dir = Path(__file__).parent.parent / "tests"

    # List of files to update
    files_to_update = [
        "test_policies.py",
        "test_e2e_cancel.py",
        "test_cancel.py",
        "test_template_separation.py",
        "test_output_template.py",
        "test_push.py",
        "test_push_mark_published_mode.py",
        "test_partial_issues.py",
        "test_inclusion_policy.py",
        "test_default_template.py",
        "test_category_validation.py",
    ]

    for filename in files_to_update:
        file_path = test_dir / filename
        if file_path.exists():
            update_file(file_path)
        else:
            print(f"  ✗ File not found: {filename}")

if __name__ == "__main__":
    main()
