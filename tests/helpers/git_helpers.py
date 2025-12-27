# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Helper functions for creating test git repositories."""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from git import Repo, Actor
from datetime import datetime, timedelta, timezone

# Import for database sync
from release_tool.models import Commit as CommitModel, Author
from release_tool.db import Database


def init_git_repo(path: Path) -> Repo:
    """
    Initialize a git repository.

    Args:
        path: Path to repository

    Returns:
        GitPython Repo object
    """
    repo = Repo.init(path)

    # Configure git user (required for commits) and disable GPG signing for tests
    with repo.config_writer() as config:
        config.set_value('user', 'name', 'Test User')
        config.set_value('user', 'email', 'test@example.com')
        # Disable GPG signing for tags and commits in test repos
        config.set_value('tag', 'gpgSign', 'false')
        config.set_value('commit', 'gpgSign', 'false')
        # Set initial branch name to 'main' for consistency across git versions
        config.set_value('init', 'defaultBranch', 'main')

    # Create initial commit to establish the 'main' branch
    # (branch doesn't exist until first commit)
    initial_file = path / '.gitkeep'
    initial_file.write_text('')
    repo.index.add(['.gitkeep'])
    repo.index.commit('Initial commit')

    # Ensure we're on 'main' branch (rename if needed)
    if repo.active_branch.name != 'main':
        repo.active_branch.rename('main')

    return repo


def create_commit(
    repo: Repo,
    message: str,
    pr_number: Optional[int] = None,
    author_name: str = "Test User",
    author_email: str = "test@example.com",
    date: Optional[datetime] = None,
    files: Optional[Dict[str, str]] = None
) -> str:
    """
    Create a commit in the repository.

    Args:
        repo: GitPython Repo object
        message: Commit message (PR number will be appended if provided)
        pr_number: Pull request number to include in message
        author_name: Author name
        author_email: Author email
        date: Commit date (defaults to current time)
        files: Dictionary of {filename: content} to create/modify

    Returns:
        Commit SHA
    """
    # Create/modify files
    if files:
        for filename, content in files.items():
            file_path = Path(repo.working_dir) / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            repo.index.add([filename])
    else:
        # Create a dummy file if no files specified
        # Count commits safely (repo might be empty)
        try:
            commit_count = len(list(repo.iter_commits()))
        except ValueError:
            # No commits yet
            commit_count = 0

        dummy_file = Path(repo.working_dir) / f"file_{commit_count}.txt"
        dummy_file.write_text(f"Content for {message}")
        repo.index.add([str(dummy_file.relative_to(repo.working_dir))])

    # Format commit message with PR number if provided
    if pr_number:
        full_message = f"{message} (#{pr_number})"
    else:
        full_message = message

    # Create commit
    author = Actor(author_name, author_email)
    commit_date = date or datetime.now()

    commit = repo.index.commit(
        full_message,
        author=author,
        committer=author,
        author_date=commit_date,
        commit_date=commit_date
    )

    return commit.hexsha


def create_tag(repo: Repo, tag_name: str, message: Optional[str] = None) -> None:
    """
    Create a git tag.

    Args:
        repo: GitPython Repo object
        tag_name: Tag_name (e.g., "v1.0.0")
        message: Optional tag message (creates annotated tag if provided)
    """
    if message:
        # Create annotated tag with message
        repo.git.tag('-a', tag_name, '-m', message)
    else:
        # Create lightweight tag directly using TagReference
        from git.refs.tag import TagReference
        TagReference.create(repo, tag_name)


def create_merge_commit(
    repo: Repo,
    pr_number: int,
    pr_title: str,
    branch_name: str = "feature/test",
    num_commits: int = 1,
    base_date: Optional[datetime] = None
) -> List[str]:
    """
    Create a realistic merge commit with PR information.

    This simulates a GitHub PR merge with:
    - Feature branch commits
    - Merge commit with PR reference

    Args:
        repo: GitPython Repo object
        pr_number: Pull request number
        pr_title: Pull request title
        branch_name: Name of the feature branch
        num_commits: Number of commits in the PR
        base_date: Base date for commits (increments for each commit)

    Returns:
        List of commit SHAs (including merge commit)
    """
    commit_shas = []
    current_date = base_date or datetime.now()

    # Get current branch (usually master/main)
    original_branch = repo.active_branch.name

    # Create feature branch
    feature_branch = repo.create_head(branch_name)
    feature_branch.checkout()

    # Create commits on feature branch
    for i in range(num_commits):
        commit_date = current_date + timedelta(minutes=i)
        sha = create_commit(
            repo,
            f"{pr_title} - commit {i+1}",
            date=commit_date
        )
        commit_shas.append(sha)

    # Switch back to original branch
    repo.heads[original_branch].checkout()

    # Merge feature branch
    merge_commit_msg = f"Merge pull request #{pr_number} from {branch_name}\n\n{pr_title}"
    repo.git.merge(branch_name, '--no-ff', m=merge_commit_msg)

    # Get merge commit SHA
    merge_sha = repo.head.commit.hexsha
    commit_shas.append(merge_sha)

    return commit_shas


class GitScenario:
    """Helper class to create complex git scenarios."""

    def __init__(self, repo: Repo, db: Optional[Database] = None, repo_id: Optional[int] = None):
        self.repo = repo
        self.db = db
        self.repo_id = repo_id
        self.base_date = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.current_date = self.base_date
        self.commit_shas = []  # Track all commit SHAs

    def advance_time(self, days: int = 0, hours: int = 0, minutes: int = 0):
        """Advance the current date."""
        self.current_date += timedelta(days=days, hours=hours, minutes=minutes)

    def add_commit(self, message: str, pr_number: Optional[int] = None, **kwargs) -> str:
        """Add a commit with auto-incrementing date and optionally sync to database."""
        sha = create_commit(
            self.repo,
            message,
            pr_number=pr_number,
            date=self.current_date,
            **kwargs
        )
        self.commit_shas.append(sha)

        # Sync to database if available
        if self.db and self.repo_id and pr_number:
            commit_model = CommitModel(
                repo_id=self.repo_id,
                sha=sha,
                message=f"{message} (#{pr_number})",
                author=Author(name="Test User", username="testuser", email="test@example.com"),
                pr_number=pr_number,
                date=self.current_date
            )
            self.db.upsert_commit(commit_model)

        self.advance_time(hours=1)
        return sha

    def add_tag(self, tag_name: str, message: Optional[str] = None):
        """Add a tag to current commit."""
        create_tag(self.repo, tag_name, message)

    def create_release_scenario_rc_sequence(self) -> Dict[str, Any]:
        """
        Create a realistic RC release scenario:
        - v1.0.0 (final release)
        - v1.1.0-rc.1
        - v1.1.0-rc.2
        - v1.1.0-rc.3
        - Uncommitted changes for rc.4

        Also creates release/1.1 branch for branch-based workflows.

        Returns:
            Dictionary with scenario details
        """
        scenario = {
            'commits': {},
            'tags': [],
            'pr_numbers': [],
            'branches': []
        }

        # Note: Initial commit already created by init_git_repo()
        # Skip creating another one to avoid duplication

        # v1.0.0 release (2 PRs)
        pr1 = 101
        pr2 = 102
        scenario['commits']['v1.0.0'] = [
            self.add_commit("Add authentication feature", pr_number=pr1),
            self.add_commit("Add user management", pr_number=pr2)
        ]
        scenario['pr_numbers'].extend([pr1, pr2])
        self.add_tag("v1.0.0")
        scenario['tags'].append("v1.0.0")
        self.advance_time(days=7)

        # Create release/1.1 branch for 1.1.x releases
        release_branch = self.repo.create_head("release/1.1")
        scenario['branches'].append("release/1.1")

        # v1.1.0-rc.1 (2 PRs)
        pr3 = 103
        pr4 = 104
        scenario['commits']['v1.1.0-rc.1'] = [
            self.add_commit("Add dashboard feature", pr_number=pr3),
            self.add_commit("Add reporting module", pr_number=pr4)
        ]
        scenario['pr_numbers'].extend([pr3, pr4])
        self.add_tag("v1.1.0-rc.1")
        scenario['tags'].append("v1.1.0-rc.1")
        self.advance_time(days=3)

        # v1.1.0-rc.2 (2 PRs)
        pr5 = 105
        pr6 = 106
        scenario['commits']['v1.1.0-rc.2'] = [
            self.add_commit("Add export functionality", pr_number=pr5),
            self.add_commit("Add notification system", pr_number=pr6)
        ]
        scenario['pr_numbers'].extend([pr5, pr6])
        self.add_tag("v1.1.0-rc.2")
        scenario['tags'].append("v1.1.0-rc.2")
        self.advance_time(days=3)

        # v1.1.0-rc.3 (2 PRs)
        pr7 = 107
        pr8 = 108
        scenario['commits']['v1.1.0-rc.3'] = [
            self.add_commit("Add search feature", pr_number=pr7),
            self.add_commit("Add filtering options", pr_number=pr8)
        ]
        scenario['pr_numbers'].extend([pr7, pr8])
        self.add_tag("v1.1.0-rc.3")
        scenario['tags'].append("v1.1.0-rc.3")
        self.advance_time(days=2)

        # Uncommitted changes for v1.1.0-rc.4 (2 PRs)
        pr9 = 109
        pr10 = 110
        scenario['commits']['v1.1.0-rc.4'] = [
            self.add_commit("Add analytics dashboard", pr_number=pr9),
            self.add_commit("Add data visualization", pr_number=pr10)
        ]
        scenario['pr_numbers'].extend([pr9, pr10])

        return scenario


def parse_markdown_output(content: str) -> Dict[str, Any]:
    """
    Parse generated markdown to extract release notes.

    Args:
        content: Markdown content

    Returns:
        Dictionary with parsed information
    """
    result = {
        'title': None,
        'categories': {},
        'all_notes': [],
        'pr_numbers': []
    }

    # Extract title
    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
    if title_match:
        result['title'] = title_match.group(1)

    # Extract categories and notes
    current_category = None
    for line in content.split('\n'):
        # Category header (## or ###)
        category_match = re.match(r'^#{2,3} (.+)$', line)
        if category_match:
            current_category = category_match.group(1)
            result['categories'][current_category] = []
            continue

        # Note entry (starts with -)
        # Match formats: "- Title (#123)" or "- Test PR #123"
        note_match = re.match(r'^- (.+?)(?:\s+\(#(\d+)\))?$', line)
        if note_match and current_category:
            note_text = note_match.group(1)
            pr_number = note_match.group(2)

            # If no PR in parentheses, try to extract from title like "Test PR #123"
            if not pr_number:
                pr_in_title = re.search(r'#(\d+)', note_text)
                if pr_in_title:
                    pr_number = pr_in_title.group(1)

            note = {'text': note_text}
            if pr_number:
                note['pr_number'] = int(pr_number)
                result['pr_numbers'].append(int(pr_number))

            result['categories'][current_category].append(note)
            result['all_notes'].append(note)

    return result
