# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Unit tests for cancel command."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner
from datetime import datetime

from release_tool.commands.cancel import cancel, _check_published_status, _resolve_version_pr_issue
from release_tool.config import Config
from release_tool.db import Database
from release_tool.models import Release, PullRequest, Issue, Repository


@pytest.fixture
def test_config(tmp_path):
    """Create a test configuration."""
    db_path = tmp_path / "test.db"
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "database": {
            "path": str(db_path)
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_db(test_config):
    """Create a test database."""
    db = Database(test_config.database.path)
    db.connect()

    # Create repository
    repo = Repository(
        owner="test",
        name="repo",
        full_name="test/repo",
        url="https://github.com/test/repo"
    )
    repo_id = db.upsert_repository(repo)

    yield db, repo_id

    db.close()


def test_help_text():
    """Test cancel command help text."""
    runner = CliRunner()
    result = runner.invoke(cancel, ['--help'])

    assert result.exit_code == 0
    assert 'Cancel a release' in result.output
    assert '--pr' in result.output
    assert '--issue' in result.output
    assert '--force' in result.output
    assert '--dry-run' in result.output


def test_version_required_without_pr_or_issue(test_config):
    """Test that version or pr/issue is required."""
    runner = CliRunner()

    with patch('release_tool.commands.cancel.Database') as mock_db_class:
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.connect.return_value = None

        # Mock get_repository
        mock_repo = Mock()
        mock_repo.id = 1
        mock_db.get_repository.return_value = mock_repo

        # Mock _resolve_version_pr_issue to return all None
        with patch('release_tool.commands.cancel._resolve_version_pr_issue', return_value=(None, None, None)):
            result = runner.invoke(
                cancel,
                [],
                obj={'config': test_config, 'debug': False},
                catch_exceptions=False
            )

    assert result.exit_code != 0
    assert 'Must provide version' in result.output or 'version, --pr, or --issue' in result.output


def test_dry_run_no_api_calls(test_config, test_db):
    """Test dry-run doesn't make API calls."""
    db, repo_id = test_db
    runner = CliRunner()

    # Create a draft release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=True,
        is_prerelease=False,
        created_at=datetime.now()
    )
    db.upsert_release(release)

    with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
        result = runner.invoke(
            cancel,
            ['1.0.0', '--dry-run'],
            obj={'config': test_config, 'debug': False},
            catch_exceptions=False
        )

    # Should not create GitHub client in dry-run
    mock_client_class.assert_not_called()

    assert result.exit_code == 0
    assert 'DRY RUN' in result.output or 'Dry run' in result.output


def test_published_release_blocked_without_force(test_db):
    """Test published release is blocked without --force."""
    db, repo_id = test_db

    # Create a published release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=False,
        is_prerelease=False,
        created_at=datetime.now(),
        published_at=datetime.now()
    )
    db.upsert_release(release)

    # Test without force
    result = _check_published_status(db, repo_id, "1.0.0", force=False, debug=False)
    assert result is False


def test_published_release_allowed_with_force(test_db):
    """Test published release is allowed with --force."""
    db, repo_id = test_db

    # Create a published release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=False,
        is_prerelease=False,
        created_at=datetime.now(),
        published_at=datetime.now()
    )
    db.upsert_release(release)

    # Test with force
    result = _check_published_status(db, repo_id, "1.0.0", force=True, debug=False)
    assert result is True


def test_draft_release_allowed(test_db):
    """Test draft release is allowed without --force."""
    db, repo_id = test_db

    # Create a draft release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=True,
        is_prerelease=False,
        created_at=datetime.now(),
        published_at=None
    )
    db.upsert_release(release)

    # Test without force
    result = _check_published_status(db, repo_id, "1.0.0", force=False, debug=False)
    assert result is True


def test_cancel_with_pr_parameter(test_config, test_db):
    """Test cancel with --pr parameter."""
    db, repo_id = test_db
    runner = CliRunner()

    # Create a draft release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=True,
        is_prerelease=False,
        created_at=datetime.now()
    )
    db.upsert_release(release)

    with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_pull_request.return_value = Mock(head=Mock(ref="test-branch"))
        mock_client.close_pull_request.return_value = True
        mock_client.delete_branch.return_value = True
        mock_client.delete_release.return_value = True
        mock_client.delete_tag.return_value = True

        result = runner.invoke(
            cancel,
            ['1.0.0', '--pr', '42'],
            obj={'config': test_config, 'debug': False, 'assume_yes': True},
            catch_exceptions=False
        )

    assert result.exit_code == 0
    mock_client.close_pull_request.assert_called_once()


def test_cancel_with_issue_parameter(test_config, test_db):
    """Test cancel with --issue parameter."""
    db, repo_id = test_db
    runner = CliRunner()

    # Create a draft release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=True,
        is_prerelease=False,
        created_at=datetime.now()
    )
    db.upsert_release(release)

    with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.delete_release.return_value = True
        mock_client.delete_tag.return_value = True
        mock_client.close_issue.return_value = True

        result = runner.invoke(
            cancel,
            ['1.0.0', '--issue', '1'],
            obj={'config': test_config, 'debug': False, 'assume_yes': True},
            catch_exceptions=False
        )

    assert result.exit_code == 0
    mock_client.close_issue.assert_called_once()


def test_resolve_version_from_pr(test_db):
    """Test auto-detecting version from PR."""
    db, repo_id = test_db

    # Create a PR with version in title
    pr = PullRequest(
        repo_id=repo_id,
        number=42,
        title="Release notes for v1.2.3",
        body="Auto-generated release notes",
        state="open",
        url="https://github.com/test/repo/pull/42",
        head_branch="release-notes-v1.2.3",
        base_branch="main"
    )
    db.upsert_pull_request(pr)

    version, pr_number, issue_number = _resolve_version_pr_issue(
        db, repo_id, "test/repo", None, 42, None, debug=False
    )

    assert version == "1.2.3"
    assert pr_number == 42


def test_resolve_version_from_issue(test_db):
    """Test auto-detecting version from issue."""
    db, repo_id = test_db

    # Create an issue with version in title
    issue = Issue(
        repo_id=repo_id,
        number=1,
        key="1",
        title="Release 1.2.3",
        body="Tracking issue",
        state="open",
        url="https://github.com/test/repo/issues/1"
    )
    db.upsert_issue(issue)

    version, pr_number, issue_number = _resolve_version_pr_issue(
        db, repo_id, "test/repo", None, None, 1, debug=False
    )

    assert version == "1.2.3"
    assert issue_number == 1


def test_github_client_initialized_correctly(test_config, test_db):
    """Regression test: Ensure GitHubClient is initialized with config object, not token string."""
    db, repo_id = test_db
    runner = CliRunner()

    # Create a draft release
    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        is_draft=True,
        is_prerelease=False,
        created_at=datetime.now()
    )
    db.upsert_release(release)

    with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.delete_release.return_value = True
        mock_client.delete_tag.return_value = True

        result = runner.invoke(
            cancel,
            ['1.0.0'],
            obj={'config': test_config, 'debug': False, 'assume_yes': True},
            catch_exceptions=False
        )

        # Verify GitHubClient was called with config object (not token string)
        mock_client_class.assert_called_once()
        call_args = mock_client_class.call_args

        # The first argument should be the config object
        assert call_args[0][0] == test_config, "GitHubClient should be initialized with config object, not token string"

    assert result.exit_code == 0
