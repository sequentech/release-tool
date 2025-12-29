# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for cancel command."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner
from pathlib import Path

from release_tool.commands.cancel import cancel
from release_tool.config import Config


@pytest.fixture
def mock_github_client():
    """Create a mock GitHub client."""
    client = Mock()
    client.gh = Mock()
    client.get_release_by_tag = Mock(return_value=None)
    client.close_pull_request = Mock(return_value=True)
    client.delete_branch = Mock(return_value=True)
    client.delete_release = Mock(return_value=True)
    client.delete_tag = Mock(return_value=True)
    client.close_issue = Mock(return_value=True)
    client.find_prs_referencing_issue = Mock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.connect = Mock()
    db.close = Mock()
    db.get_issue_association = Mock(return_value=None)
    db.get_issue_association_by_issue = Mock(return_value=None)
    db.get_repository = Mock(return_value=None)
    db.cursor = Mock()
    db.cursor.execute = Mock()
    db.conn = Mock()
    db.conn.commit = Mock()
    return db


@pytest.fixture
def config():
    """Create a test configuration."""
    return Config.from_dict({
        'repository': {'code_repo': 'test/repo'},
        'github': {'token': 'test_token'},
        'version_policy': {'tag_prefix': 'v'}
    })


def test_cancel_help(config):
    """Test that cancel command help works."""
    runner = CliRunner()
    result = runner.invoke(cancel, ['--help'])
    assert result.exit_code == 0
    assert 'Cancel a release' in result.output
    assert '--force' in result.output
    assert '--dry-run' in result.output


def test_cancel_without_version_or_issue(config):
    """Test that cancel requires version or issue."""
    runner = CliRunner()

    with patch('release_tool.commands.cancel.GitHubClient'), \
         patch('release_tool.commands.cancel.Database'):

        result = runner.invoke(
            cancel,
            [],
            obj={'config': config, 'debug': False}
        )

        assert result.exit_code == 1
        assert 'Could not determine version' in result.output


def test_cancel_dry_run(config, mock_github_client, mock_db):
    """Test cancel in dry-run mode."""
    runner = CliRunner()

    # Mock database to return issue association
    mock_db.get_issue_association.return_value = {
        'issue_number': 42,
        'issue_url': 'https://github.com/test/repo/issues/42'
    }

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['1.2.3', '--dry-run'],
            obj={'config': config, 'debug': False, 'auto': True}
        )

        # Should succeed with dry-run
        assert result.exit_code == 0
        assert 'DRY RUN' in result.output
        assert 'Would delete GitHub release' in result.output
        assert 'Would delete git tag' in result.output

        # Should not actually call deletion methods
        mock_github_client.delete_release.assert_not_called()
        mock_github_client.delete_tag.assert_not_called()


def test_cancel_published_release_without_force(config, mock_github_client, mock_db):
    """Test that cancel blocks published releases without --force."""
    runner = CliRunner()

    # Mock a published release
    mock_release = Mock()
    mock_release.draft = False
    mock_github_client.get_release_by_tag.return_value = mock_release

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['1.2.3'],
            obj={'config': config, 'debug': False, 'auto': True}
        )

        # Should fail without --force
        assert result.exit_code == 1
        assert 'Cannot cancel published release' in result.output
        assert 'Use --force' in result.output


def test_cancel_published_release_with_force(config, mock_github_client, mock_db):
    """Test that cancel allows published releases with --force."""
    runner = CliRunner()

    # Mock a published release
    mock_release = Mock()
    mock_release.draft = False
    mock_github_client.get_release_by_tag.return_value = mock_release

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['1.2.3', '--force', '--dry-run'],
            obj={'config': config, 'debug': False, 'auto': True}
        )

        # Should succeed with --force
        assert result.exit_code == 0
        assert 'DRY RUN' in result.output


def test_cancel_with_pr_and_branch(config, mock_github_client, mock_db):
    """Test cancel with PR and branch detection."""
    runner = CliRunner()

    # Mock PR search to return a PR
    mock_github_client.find_prs_referencing_issue.return_value = [123]

    # Mock getting PR details
    mock_pr = Mock()
    mock_pr.head = Mock()
    mock_pr.head.ref = 'release/1.2'

    mock_repo = Mock()
    mock_repo.get_pull.return_value = mock_pr
    mock_github_client.gh.get_repo.return_value = mock_repo

    # Mock database to return issue association
    mock_db.get_issue_association.return_value = {
        'issue_number': 42,
        'issue_url': 'https://github.com/test/repo/issues/42'
    }

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['1.2.3', '--dry-run'],
            obj={'config': config, 'debug': False, 'auto': True}
        )

        assert result.exit_code == 0
        assert 'PR: #123' in result.output or 'Found PR' in result.output
        assert 'release/1.2' in result.output or 'Branch:' in result.output


def test_cancel_with_issue_parameter(config, mock_github_client, mock_db):
    """Test cancel with --issue parameter."""
    runner = CliRunner()

    # Mock database to return version from issue
    mock_db.get_issue_association_by_issue.return_value = {
        'version': '1.2.3',
        'issue_url': 'https://github.com/test/repo/issues/42'
    }

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['--issue', '42', '--dry-run'],
            obj={'config': config, 'debug': False, 'auto': True}
        )

        assert result.exit_code == 0
        assert '1.2.3' in result.output
        assert 'Issue: #42' in result.output


def test_cancel_executes_deletions(config, mock_github_client, mock_db):
    """Test that cancel actually calls deletion methods."""
    runner = CliRunner()

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['1.2.3'],
            obj={'config': config, 'debug': False, 'auto': True, 'assume_yes': True},
            catch_exceptions=False
        )

        # Should succeed
        assert result.exit_code == 0

        # Should call deletion methods
        mock_github_client.delete_release.assert_called_once_with('test/repo', 'v1.2.3')
        mock_github_client.delete_tag.assert_called_once_with('test/repo', 'v1.2.3')

        # Should delete from database
        assert mock_db.cursor.execute.called
        assert mock_db.conn.commit.called


def test_cancel_stops_on_failure(config, mock_github_client, mock_db):
    """Test that cancel stops on first failure."""
    runner = CliRunner()

    # Make delete_release fail
    mock_github_client.delete_release.return_value = False

    with patch('release_tool.commands.cancel.GitHubClient', return_value=mock_github_client), \
         patch('release_tool.commands.cancel.Database', return_value=mock_db):

        result = runner.invoke(
            cancel,
            ['1.2.3'],
            obj={'config': config, 'debug': False, 'auto': True, 'assume_yes': True}
        )

        # Should fail
        assert result.exit_code == 1
        assert 'Failed to delete release' in result.output or 'Aborting' in result.output

        # Should NOT call subsequent operations (delete_tag)
        mock_github_client.delete_tag.assert_not_called()
