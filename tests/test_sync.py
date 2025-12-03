# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for sync functionality."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from release_tool.config import Config
from release_tool.db import Database
from release_tool.sync import SyncManager
from release_tool.github_utils import GitHubClient
from release_tool.models import Ticket, PullRequest, Author, Label


@pytest.fixture
def test_config():
    """Create test configuration."""
    config_dict = {
        "repository": {
            "code_repo": "sequentech/step",
            "ticket_repos": ["sequentech/meta"],
            "default_branch": "main"
        },
        "github": {
            "token": "test_token"
        },
        "sync": {
            "parallel_workers": 2,
            "show_progress": False,
            "clone_code_repo": False
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_db(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_sync.db"
    db = Database(str(db_path))
    db.connect()
    yield db
    db.close()


@pytest.fixture
def mock_github():
    """Create mock GitHub client."""
    mock = Mock(spec=GitHubClient)
    return mock


def test_sync_metadata_tracking(test_db):
    """Test sync metadata CRUD operations."""
    # No sync initially
    last_sync = test_db.get_last_sync("sequentech/meta", "tickets")
    assert last_sync is None

    # Update sync metadata
    test_db.update_sync_metadata(
        "sequentech/meta",
        "tickets",
        cutoff_date="2024-01-01",
        total_fetched=50
    )

    # Should have sync timestamp now
    last_sync = test_db.get_last_sync("sequentech/meta", "tickets")
    assert last_sync is not None
    assert isinstance(last_sync, datetime)

    # Get all sync status
    status = test_db.get_all_sync_status()
    assert len(status) == 1
    assert status[0]['repo_full_name'] == "sequentech/meta"
    assert status[0]['entity_type'] == "tickets"
    assert status[0]['total_fetched'] == 50


def test_get_existing_ticket_numbers(test_db):
    """Test retrieval of existing ticket numbers."""
    from release_tool.models import Repository, Ticket, Label

    # Create repository
    repo = Repository(
        owner="sequentech",
        name="meta",
        full_name="sequentech/meta",
        url="https://github.com/sequentech/meta"
    )
    repo_id = test_db.upsert_repository(repo)

    # Add some tickets
    for num in [1, 5, 10, 25]:
        ticket = Ticket(
            repo_id=repo_id,
            number=num,
            key=f"#{num}",
            title=f"Test ticket {num}",
            body="",
            state="open",
            labels=[],
            url=f"https://github.com/sequentech/meta/issues/{num}",
            created_at=datetime.now(),
            closed_at=None
        )
        test_db.upsert_ticket(ticket)

    # Get existing numbers
    existing = test_db.get_existing_ticket_numbers("sequentech/meta")
    assert existing == {1, 5, 10, 25}


def test_get_existing_pr_numbers(test_db):
    """Test retrieval of existing PR numbers."""
    from release_tool.models import Repository, PullRequest, Author

    # Create repository
    repo = Repository(
        owner="sequentech",
        name="step",
        full_name="sequentech/step",
        url="https://github.com/sequentech/step"
    )
    repo_id = test_db.upsert_repository(repo)

    # Add some PRs
    author = Author(name="Test User", username="testuser")
    for num in [10, 20, 30]:
        pr = PullRequest(
            repo_id=repo_id,
            number=num,
            title=f"Test PR {num}",
            body="",
            state="merged",
            merged_at=datetime.now(),
            author=author,
            base_branch="main",
            head_branch="feature",
            head_sha="abc123",
            labels=[],
            url=f"https://github.com/sequentech/step/pull/{num}"
        )
        test_db.upsert_pull_request(pr)

    # Get existing numbers
    existing = test_db.get_existing_pr_numbers("sequentech/step")
    assert existing == {10, 20, 30}


def test_config_get_ticket_repos(test_config):
    """Test getting ticket repos from config."""
    ticket_repos = test_config.get_ticket_repos()
    assert ticket_repos == ["sequentech/meta"]


def test_config_get_ticket_repos_defaults_to_code_repo():
    """Test that ticket_repos defaults to code_repo if not specified."""
    config_dict = {
        "repository": {
            "code_repo": "sequentech/step"
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)
    ticket_repos = config.get_ticket_repos()
    assert ticket_repos == ["sequentech/step"]


def test_config_get_code_repo_path_default(test_config):
    """Test default code repo path generation."""
    path = test_config.get_code_repo_path()
    assert "step" in path
    assert ".release_tool_cache" in path


def test_config_get_code_repo_path_custom():
    """Test custom code repo path."""
    config_dict = {
        "repository": {
            "code_repo": "sequentech/step"
        },
        "github": {
            "token": "test_token"
        },
        "sync": {
            "code_repo_path": "/custom/path/to/repo"
        }
    }
    config = Config.from_dict(config_dict)
    path = config.get_code_repo_path()
    assert path == "/custom/path/to/repo"


def test_sync_config_defaults():
    """Test sync configuration defaults."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        }
    }
    config = Config.from_dict(config_dict)

    assert config.sync.parallel_workers == 20
    assert config.sync.show_progress is True
    assert config.sync.clone_code_repo is True
    assert config.sync.cutoff_date is None


def test_sync_config_cutoff_date():
    """Test sync configuration with cutoff date."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "sync": {
            "cutoff_date": "2024-01-01"
        }
    }
    config = Config.from_dict(config_dict)
    assert config.sync.cutoff_date == "2024-01-01"


@patch('release_tool.sync.subprocess.run')
def test_sync_git_repository_clone(mock_run, test_config, tmp_path):
    """Test cloning a new git repository."""
    # Update config to use temp path
    test_config.sync.code_repo_path = str(tmp_path / "test_repo")

    mock_db = Mock(spec=Database)
    mock_github = Mock(spec=GitHubClient)

    sync_manager = SyncManager(test_config, mock_db, mock_github)

    # Mock successful clone
    mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

    repo_path = sync_manager._sync_git_repository("sequentech/step")

    # Should have called git clone
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    assert 'git' in call_args
    assert 'clone' in call_args
    assert "sequentech/step" in ' '.join(call_args)


@patch('release_tool.sync.subprocess.run')
def test_sync_git_repository_update(mock_run, test_config, tmp_path):
    """Test updating an existing git repository."""
    # Create fake repo directory with .git
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    test_config.sync.code_repo_path = str(repo_path)

    mock_db = Mock(spec=Database)
    mock_github = Mock(spec=GitHubClient)

    sync_manager = SyncManager(test_config, mock_db, mock_github)

    # Mock successful fetch and reset
    mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

    result_path = sync_manager._sync_git_repository("sequentech/step")

    # Should have called git fetch and git reset
    assert mock_run.call_count >= 2
    calls = [call[0][0] for call in mock_run.call_args_list]

    # Check for fetch
    fetch_call = [c for c in calls if 'fetch' in c]
    assert len(fetch_call) > 0

    # Check for reset
    reset_call = [c for c in calls if 'reset' in c]
    assert len(reset_call) > 0


def test_incremental_sync_filters_existing(test_config, test_db, mock_github):
    """Test that incremental sync only fetches new items."""
    from release_tool.models import Repository

    # Create repository in DB
    repo = Repository(
        owner="sequentech",
        name="meta",
        full_name="sequentech/meta",
        url="https://github.com/sequentech/meta"
    )
    repo_id = test_db.upsert_repository(repo)

    # Add existing tickets
    for num in [1, 2, 3]:
        ticket = Ticket(
            repo_id=repo_id,
            number=num,
            key=f"#{num}",
            title=f"Test {num}",
            body="",
            state="open",
            labels=[],
            url=f"https://github.com/sequentech/meta/issues/{num}",
            created_at=datetime.now(),
            closed_at=None
        )
        test_db.upsert_ticket(ticket)

    # Mock GitHub to return all tickets (including existing)
    mock_github.search_ticket_numbers.return_value = [1, 2, 3, 4, 5, 6]

    sync_manager = SyncManager(test_config, test_db, mock_github)

    # Get ticket numbers to fetch
    to_fetch = sync_manager._get_ticket_numbers_to_fetch("sequentech/meta", None)

    # Should only fetch new tickets (4, 5, 6)
    assert set(to_fetch) == {4, 5, 6}


def test_parallel_workers_config():
    """Test that parallel_workers configuration is respected."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "sync": {
            "parallel_workers": 20
        }
    }
    config = Config.from_dict(config_dict)

    assert config.sync.parallel_workers == 20

    mock_db = Mock(spec=Database)
    mock_github = Mock(spec=GitHubClient)

    sync_manager = SyncManager(config, mock_db, mock_github)
    assert sync_manager.parallel_workers == 20
