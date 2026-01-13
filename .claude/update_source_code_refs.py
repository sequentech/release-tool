#!/usr/bin/env python3
"""Script to update source code references from code_repo to get_primary_code_repo().link."""

import re
from pathlib import Path

def update_file(file_path: Path):
    """Update a single file."""
    print(f"Updating {file_path}...")

    content = file_path.read_text()
    original_content = content

    # Replace config.repository.code_repo with config.get_primary_code_repo().link
    # But be careful with comments and documentation
    pattern = r'(\w+)\.repository\.code_repo(?!\w)'

    def replacer(match):
        var_name = match.group(1)
        return f'{var_name}.get_primary_code_repo().link'

    content = re.sub(pattern, replacer, content)

    if content != original_content:
        file_path.write_text(content)
        print(f"  ✓ Updated {file_path.name}")
    else:
        print(f"  - No changes needed for {file_path.name}")

def main():
    """Main entry point."""
    commands_dir = Path(__file__).parent.parent / "src" / "release_tool" / "commands"

    # List of command files to update
    files_to_update = [
        "push.py",
        "cancel.py",
        "list_releases.py",
        "pull.py",
        "generate.py",
        "merge.py",
    ]

    for filename in files_to_update:
        file_path = commands_dir / filename
        if file_path.exists():
            update_file(file_path)
        else:
            print(f"  ✗ File not found: {filename}")

if __name__ == "__main__":
    main()
