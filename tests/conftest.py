# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Shared pytest fixtures for end-to-end tests."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from git import Repo

from release_tool.db import Database
from release_tool.config import Config
from release_tool.models import PullRequest, Issue, Label, Repository
from helpers.git_helpers import init_git_repo, GitScenario
from helpers.config_helpers import create_test_config, write_config_file


@pytest.fixture
def tmp_git_repo(tmp_path):
    """
    Create a temporary git repository.

    Returns:
        Tuple of (repo_path, Repo object)
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    repo = init_git_repo(repo_path)

    yield repo_path, repo

    # Cleanup handled by tmp_path


@pytest.fixture
def git_scenario(tmp_git_repo, test_db):
    """
    Create a GitScenario helper for building complex git histories.

    Returns:
        GitScenario instance with database sync
    """
    repo_path, repo = tmp_git_repo
    db, repo_id = test_db
    scenario = GitScenario(repo, db=db, repo_id=repo_id)

    return scenario


@pytest.fixture
def test_db(tmp_path):
    """
    Create an in-memory test database with test data.

    Returns:
        Database instance
    """
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    db.connect()  # Initialize database connection and schema

    # Create test repository
    test_repo = Repository(
        owner="test",
        name="repo",
        full_name="test/repo",
        url="https://github.com/test/repo"
    )
    repo_id = db.upsert_repository(test_repo)

    yield db, repo_id

    # Cleanup
    db.close()


@pytest.fixture
def mock_github_client():
    """
    Create a mock GitHub client that doesn't make external calls.

    Returns:
        Mock GitHub client
    """
    client = Mock()

    # Mock common methods
    client.get_pull_request = Mock(return_value=None)
    client.get_issue = Mock(return_value=None)
    client.create_release = Mock(return_value={'html_url': 'https://github.com/test/repo/releases/tag/v1.0.0'})
    client.create_pull_request = Mock(return_value={'html_url': 'https://github.com/test/repo/pull/1'})

    return client


@pytest.fixture
def test_config_dict():
    """
    Create a basic test configuration dictionary.

    Returns:
        Configuration dictionary
    """
    return create_test_config(code_repo="test/repo")


@pytest.fixture
def test_config(test_config_dict):
    """
    Create a Config object from test configuration.

    Returns:
        Config instance
    """
    return Config.from_dict(test_config_dict)


@pytest.fixture
def test_config_file(tmp_path, test_config_dict):
    """
    Create a temporary config file.

    Returns:
        Path to config file
    """
    config_path = tmp_path / "config.yaml"
    write_config_file(config_path, test_config_dict)

    return config_path


@pytest.fixture
def populated_db(test_db):
    """
    Create a database populated with test PRs and issues.

    Returns:
        Tuple of (Database, repo_id, test_data)
    """
    db, repo_id = test_db

    test_data = {
        'prs': {},
        'issues': {}
    }

    # Create test PRs (101-110)
    for pr_num in range(101, 111):
        pr = PullRequest(
            repo_id=repo_id,
            number=pr_num,
            title=f"Test PR #{pr_num}",
            body=f"Test PR body for #{pr_num}",
            state="closed",
            merged=True,
            labels=[Label(name="enhancement")],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            closed_at="2024-01-01T00:00:00Z",
            merged_at="2024-01-01T00:00:00Z",
            merge_commit_sha=f"abc{pr_num}def",
            head_ref=f"feature/test-{pr_num}",
            base_ref="main"
        )
        db.upsert_pull_request(pr)
        test_data['prs'][pr_num] = pr

    # Create corresponding issues
    for issue_num in range(101, 111):
        issue = Issue(
            repo_id=repo_id,
            number=issue_num,
            key=f"#{issue_num}",  # Issue key (e.g., "#101")
            title=f"Test Issue #{issue_num}",
            body=f"Test issue body for #{issue_num}",
            state="closed",
            labels=[Label(name="enhancement")],
            created_at="2024-01-01T00:00:00Z",
            closed_at="2024-01-01T00:00:00Z"
        )
        db.upsert_issue(issue)
        test_data['issues'][issue_num] = issue

    yield db, repo_id, test_data


@pytest.fixture
def mock_github_api():
    """
    Patch GitHub API calls to avoid external dependencies.

    Use as a context manager or decorator.
    """
    with patch('release_tool.github_utils.GitHubClient') as mock_client_class:
        # Create a mock instance
        mock_instance = Mock()

        # Mock the class to return our instance
        mock_client_class.return_value = mock_instance

        # Setup default return values
        mock_instance.get_pull_request.return_value = None
        mock_instance.get_issue.return_value = None

        yield mock_instance
