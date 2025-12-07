# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for publish command just-publish mode functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner

from release_tool.commands.publish import publish
from release_tool.config import Config


@pytest.fixture
def test_config():
    """Create a test configuration."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "create_github_release": False,
            "create_pr": False,
            "draft_release": False,
            "prerelease": "auto",
            "draft_output_path": ".release_tool_cache/draft-releases/{{repo}}/{{version}}.md",
            "pr_templates": {
                "branch_template": "docs/{{version}}/{{target_branch}}",
                "title_template": "Release notes for {{version}}",
                "body_template": "Automated release notes for version {{version}}."
            }
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_notes_file(tmp_path):
    """Create a temporary release notes file."""
    notes_file = tmp_path / "release_notes.md"
    notes_file.write_text("# Release 1.0.0\n\nTest release notes content.")
    return notes_file


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_dry_run(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode in dry-run shows expected output."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None  # No existing release in DB
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--dry-run', '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config}
    )
    
    # Should show dry-run output for just-publish mode
    assert result.exit_code == 0
    assert 'DRY RUN' in result.output
    assert 'Would mark existing GitHub release as published' in result.output
    assert 'test/repo' in result.output
    assert 'Tag: v1' in result.output and '0.0' in result.output
    
    # Should not call GitHub API in dry-run
    mock_gh_client.assert_not_called()


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_no_existing_release(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode fails when no existing release found."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - no existing release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    mock_gh_instance.get_release_by_tag.return_value = None
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config}
    )
    
    # Should fail with error
    assert result.exit_code == 1
    assert 'No existing GitHub release found' in result.output
    assert 'Use --release-mode published or draft to create a new release' in result.output
    
    # Should not call update_release
    mock_gh_instance.update_release.assert_not_called()


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_marks_existing_release_as_published(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode successfully marks existing release as published."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - existing draft release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0"
    mock_existing_release.title = "Release 1.0.0"
    mock_existing_release.body = "Original release notes"
    mock_existing_release.prerelease = False
    mock_existing_release.draft = True
    mock_existing_release.target_commitish = "main"
    
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config}
    )
    
    # Should succeed
    assert result.exit_code == 0
    assert 'Marking existing GitHub release as published' in result.output
    assert 'marked as published successfully' in result.output
    
    # Verify update_release was called with draft=False
    mock_gh_instance.update_release.assert_called_once()
    call_args = mock_gh_instance.update_release.call_args
    assert call_args.kwargs['draft'] == False
    assert call_args.kwargs['name'] == "Release 1.0.0"
    assert call_args.kwargs['body'] == "Original release notes"
    assert call_args.kwargs['prerelease'] == False
    assert call_args.kwargs['target_commitish'] == "main"


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_preserves_release_properties(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode preserves all existing release properties."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - existing prerelease
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0-beta.1"
    mock_existing_release.title = "Beta Release 1.0.0-beta.1"
    mock_existing_release.body = "Beta release notes with special content"
    mock_existing_release.prerelease = True
    mock_existing_release.draft = True
    mock_existing_release.target_commitish = "develop"
    
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0-beta.1"
    
    result = runner.invoke(
        publish,
        ['1.0.0-beta.1', '-f', str(test_notes_file), '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config}
    )
    
    # Should succeed
    assert result.exit_code == 0
    
    # Verify update_release preserved all properties except draft
    mock_gh_instance.update_release.assert_called_once()
    call_args = mock_gh_instance.update_release.call_args
    assert call_args.kwargs['draft'] == False  # Changed to published
    assert call_args.kwargs['name'] == "Beta Release 1.0.0-beta.1"  # Preserved
    assert call_args.kwargs['body'] == "Beta release notes with special content"  # Preserved
    assert call_args.kwargs['prerelease'] == True  # Preserved
    assert call_args.kwargs['target_commitish'] == "develop"  # Preserved


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_skips_tag_creation(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode does not create or push tags."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - existing release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0"
    mock_existing_release.title = "Release 1.0.0"
    mock_existing_release.body = "Original release notes"
    mock_existing_release.prerelease = False
    mock_existing_release.draft = True
    mock_existing_release.target_commitish = "main"
    
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config}
    )
    
    # Should succeed
    assert result.exit_code == 0
    
    # Verify tag operations were NOT called
    mock_git_instance.create_tag.assert_not_called()
    mock_git_instance.push_tag.assert_not_called()
    mock_git_instance.tag_exists.assert_not_called()


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_with_debug_output(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode shows debug output when enabled."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - existing release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0"
    mock_existing_release.title = "Release 1.0.0"
    mock_existing_release.body = "Original release notes"
    mock_existing_release.prerelease = False
    mock_existing_release.draft = True
    mock_existing_release.target_commitish = "main"
    
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config, 'debug': True}
    )
    
    # Should succeed with debug output
    assert result.exit_code == 0
    assert 'Existing release URL:' in result.output
    assert 'Current draft status:' in result.output


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_just_publish_mode_fails_when_update_fails(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test just-publish mode fails gracefully when GitHub update fails."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - existing release but update fails
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0"
    mock_existing_release.title = "Release 1.0.0"
    mock_existing_release.body = "Original release notes"
    mock_existing_release.prerelease = False
    mock_existing_release.draft = True
    mock_existing_release.target_commitish = "main"
    
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = None  # Simulate failure
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--release-mode', 'just-publish'],
        obj={'config': test_config}
    )
    
    # Should fail
    assert result.exit_code == 1
    assert 'Failed to update GitHub release' in result.output
