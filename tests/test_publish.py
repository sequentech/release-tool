# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for publish command functionality."""

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


def test_dry_run_shows_output_without_api_calls(test_config, test_notes_file):
    """Test that dry-run shows expected output without making API calls."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client:
        result = runner.invoke(
            publish,
            ['1.0.0', '-f', str(test_notes_file), '--dry-run', '--release'],
            obj={'config': test_config}
        )

        # Should not create GitHub client in dry-run
        mock_client.assert_not_called()

        # Should show dry-run banner
        assert 'DRY RUN' in result.output
        assert 'Publish release 1.0.0' in result.output

        # Should show what would be created
        assert 'Would create' in result.output
        assert 'test/repo' in result.output
        assert 'v1.0.0' in result.output

        # Should exit successfully
        assert result.exit_code == 0


def test_dry_run_with_pr_flag(test_config, test_notes_file):
    """Test dry-run with PR creation flag."""
    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--dry-run', '--pr', '--no-release'],
        obj={'config': test_config}
    )

    assert 'Would create pull request' in result.output
    assert 'Would NOT create GitHub release' in result.output
    assert result.exit_code == 0


def test_dry_run_with_draft_and_prerelease(test_config, test_notes_file):
    """Test dry-run with draft and prerelease flags."""
    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0-rc.1', '-f', str(test_notes_file), '--dry-run', '--release', '--release-mode', 'draft', '--prerelease', 'true'],
        obj={'config': test_config}
    )

    assert 'DRY RUN' in result.output
    assert 'Draft' in result.output or 'draft' in result.output
    assert result.exit_code == 0


def test_config_defaults_used_when_no_cli_flags(test_config, test_notes_file):
    """Test that config defaults are used when CLI flags are not provided."""
    # Set config defaults
    test_config.output.create_github_release = True
    test_config.output.release_mode = "draft"

    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_release_by_tag.return_value = None  # No existing release
        mock_client.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
        
        # Mock git operations for tag creation
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.get_version_tags.return_value = []

        result = runner.invoke(
            publish,
            ['1.0.0', '-f', str(test_notes_file)],
            obj={'config': test_config}
        )

        # Should create release with draft=True (from config)
        mock_client.create_release.assert_called_once()
        call_args = mock_client.create_release.call_args
        assert call_args.kwargs['draft'] == True
        assert result.exit_code == 0


def test_cli_flags_override_config(test_config, test_notes_file):
    """Test that CLI flags override config values."""
    # Set config to not create release
    test_config.output.create_github_release = False

    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_release_by_tag.return_value = None  # No existing release
        mock_client.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
        
        # Mock git operations for tag creation
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.get_version_tags.return_value = []

        # Override with --release flag
        result = runner.invoke(
            publish,
            ['1.0.0', '-f', str(test_notes_file), '--release'],
            obj={'config': test_config}
        )

        # Should create release despite config saying False
        mock_client.create_release.assert_called_once()
        assert result.exit_code == 0


def test_debug_mode_shows_verbose_output(test_config, test_notes_file):
    """Test that debug mode shows verbose information."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient'):
        result = runner.invoke(
            publish,
            ['1.0.0', '-f', str(test_notes_file), '--dry-run'],
            obj={'config': test_config, 'debug': True}
        )

        # Should show debug output
        assert 'Debug Mode:' in result.output
        assert 'Repository:' in result.output or 'Configuration' in result.output
        assert 'Version:' in result.output
        assert result.exit_code == 0


def test_debug_mode_shows_docusaurus_preview(test_config, test_notes_file, tmp_path):
    """Test that debug mode shows Docusaurus file preview when configured."""
    # Create a docusaurus file
    doc_file = tmp_path / "doc_release.md"
    doc_file.write_text("---\nid: release-1.0.0\n---\n# Release 1.0.0\n\nDocusaurus notes")

    # Configure doc_output_path
    test_config.output.doc_output_path = str(doc_file)

    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--dry-run'],
        obj={'config': test_config, 'debug': True}
    )

    # Should show doc file info in debug mode
    assert 'Docusaurus' in result.output
    assert 'doc_release.md' in result.output  # Just check for filename, not full path
    assert 'Docusaurus notes preview' in result.output or 'Docusaurus file length' in result.output or 'File exists' in result.output
    assert result.exit_code == 0


def test_error_handling_with_debug(test_config, test_notes_file):
    """Test that debug mode re-raises exceptions with stack trace."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.SemanticVersion.parse', side_effect=Exception("Test error")):
        result = runner.invoke(
            publish,
            ['invalid', '-f', str(test_notes_file)],
            obj={'config': test_config, 'debug': True}
        )

        # Should show the exception
        assert result.exit_code != 0
        assert 'Test error' in result.output or result.exception


def test_error_handling_without_debug(test_config, test_notes_file):
    """Test that non-debug mode shows error message without stack trace."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.SemanticVersion.parse', side_effect=Exception("Test error")):
        result = runner.invoke(
            publish,
            ['invalid', '-f', str(test_notes_file)],
            obj={'config': test_config}
        )

        # Should show error message
        assert result.exit_code != 0
        assert 'Error:' in result.output


def test_auto_detect_prerelease_version(test_config, test_notes_file):
    """Test that prerelease is auto-detected from version when set to 'auto'."""
    runner = CliRunner()

    # Ensure config is set to "auto" (default)
    test_config.output.prerelease = "auto"

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_release_by_tag.return_value = None  # No existing release
        mock_client.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0-rc.1"
        
        # Mock git operations for tag creation
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.get_version_tags.return_value = []

        result = runner.invoke(
            publish,
            ['1.0.0-rc.1', '-f', str(test_notes_file), '--release'],
            obj={'config': test_config}
        )

        # Should detect as prerelease
        assert 'Auto-detected as prerelease' in result.output

        # Should call create_release with prerelease=True
        call_args = mock_client.create_release.call_args
        assert call_args.kwargs['prerelease'] == True
        assert result.exit_code == 0


def test_dry_run_shows_release_notes_preview(test_config, test_notes_file):
    """Test that dry-run shows a preview of the release notes."""
    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--dry-run', '--release'],
        obj={'config': test_config}
    )

    # Should show preview of release notes
    assert 'Release notes preview' in result.output
    assert 'Test release notes content' in result.output
    assert result.exit_code == 0


def test_dry_run_summary_at_end(test_config, test_notes_file):
    """Test that dry-run shows summary at the end."""
    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--dry-run'],
        obj={'config': test_config}
    )

    # Should show summary
    assert 'DRY RUN complete' in result.output
    assert 'No changes were made' in result.output
    assert result.exit_code == 0


def test_docusaurus_file_detection_in_dry_run(test_config, test_notes_file, tmp_path):
    """Test that dry-run detects and reports Docusaurus file."""
    # Create a docusaurus file
    doc_file = tmp_path / "doc_release.md"
    doc_file.write_text("Docusaurus content")

    # Configure doc_output_path
    test_config.output.doc_output_path = str(doc_file)

    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--dry-run'],
        obj={'config': test_config}
    )

    # Should mention docusaurus file
    assert 'Docusaurus file' in result.output
    assert 'doc_release.md' in result.output  # Just check for filename, not full path
    assert 'Existing Docusaurus file found' in result.output or 'File exists' in result.output
    assert result.exit_code == 0


def test_pr_without_notes_file_shows_warning(test_config):
    """Test that creating PR without notes file shows warning and skips."""
    runner = CliRunner()

    with patch('release_tool.commands.publish._find_draft_releases', return_value=[]):
        result = runner.invoke(
            publish,
            ['1.0.0', '--pr', '--dry-run'],
            obj={'config': test_config}
        )

        # Should show warning about no notes available
        assert 'No draft release notes found' in result.output or 'No release notes available' in result.output


def test_prerelease_explicit_true(test_config, test_notes_file):
    """Test that --prerelease true always marks as prerelease."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_release_by_tag.return_value = None  # No existing release
        mock_client.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
        
        # Mock git operations for tag creation
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.get_version_tags.return_value = []

        # Use a stable version but force prerelease
        result = runner.invoke(
            publish,
            ['1.0.0', '-f', str(test_notes_file), '--release', '--prerelease', 'true'],
            obj={'config': test_config}
        )

        # Should call create_release with prerelease=True
        call_args = mock_client.create_release.call_args
        assert call_args.kwargs['prerelease'] == True
        assert result.exit_code == 0


def test_prerelease_explicit_false(test_config, test_notes_file):
    """Test that --prerelease false never marks as prerelease."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_release_by_tag.return_value = None  # No existing release
        mock_client.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0-rc.1"
        
        # Mock git operations for tag creation
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.get_version_tags.return_value = []

        # Use an RC version but force stable
        result = runner.invoke(
            publish,
            ['1.0.0-rc.1', '-f', str(test_notes_file), '--release', '--prerelease', 'false'],
            obj={'config': test_config}
        )

        # Should call create_release with prerelease=False
        call_args = mock_client.create_release.call_args
        assert call_args.kwargs['prerelease'] == False
        assert result.exit_code == 0


def test_auto_find_draft_notes_success(test_config, tmp_path):
    """Test successful auto-finding of draft notes."""
    # Create a draft notes file in current directory
    draft_dir = Path(".release_tool_cache") / "draft-releases" / "test-repo"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_file = draft_dir / "1.0.0.md"
    draft_file.write_text("# Release 1.0.0\n\nAuto-found draft notes")

    # Use relative path with Jinja2 syntax
    test_config.output.draft_output_path = ".release_tool_cache/draft-releases/{{code_repo}}/{{version}}.md"

    try:
        runner = CliRunner()

        with patch('release_tool.commands.publish.GitHubClient') as mock_client_class, \
             patch('release_tool.commands.publish.GitOperations') as mock_git_ops:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
            
            # Mock git operations for tag creation
            mock_git_instance = MagicMock()
            mock_git_ops.return_value = mock_git_instance
            mock_git_instance.tag_exists.return_value = False
            mock_git_instance.get_version_tags.return_value = []

            # Don't specify --notes-file, should auto-find
            result = runner.invoke(
                publish,
                ['1.0.0', '--release'],
                obj={'config': test_config},
                catch_exceptions=False
            )

            # Should find and use the draft notes
            assert 'Auto-found release notes' in result.output or result.exit_code == 0
            # Should create release
            if mock_client.create_release.called:
                assert result.exit_code == 0
    finally:
        # Cleanup
        import shutil
        if draft_file.exists():
            draft_file.unlink()
        if draft_dir.exists():
            shutil.rmtree(draft_dir.parent.parent, ignore_errors=True)


def test_auto_find_draft_notes_not_found(test_config):
    """Test error when no draft notes found."""
    runner = CliRunner()

    # Don't create any draft files
    with patch('release_tool.commands.publish._find_draft_releases', return_value=[]):
        result = runner.invoke(
            publish,
            ['1.0.0'],
            obj={'config': test_config}
        )

        # Should error and list available drafts
        assert 'No draft release notes found' in result.output
        assert result.exit_code == 1


def test_branch_creation_when_needed(test_config, test_notes_file):
    """Test that release branch is created and pushed when it doesn't exist."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_gh_client, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class:

        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None  # No existing repo/release

        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []
        mock_git_instance.tag_exists.return_value = False  # Tag doesn't exist
        mock_git_instance.branch_exists.return_value = False  # Branch doesn't exist (neither local nor remote)

        # Mock strategy to return should_create_branch=True
        mock_strategy.return_value = ("release/0.0", "main", True)

        # Mock GitHub client
        mock_gh_instance = MagicMock()
        mock_gh_client.return_value = mock_gh_instance
        mock_gh_instance.get_release_by_tag.return_value = None  # No existing release
        mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v0.0.1-rc.0"

        result = runner.invoke(
            publish,
            ['0.0.1-rc.0', '-f', str(test_notes_file), '--release'],
            obj={'config': test_config}
        )

        # Should call create_branch with correct parameters
        mock_git_instance.create_branch.assert_called_once_with("release/0.0", "main")

        # Should call push_branch
        mock_git_instance.push_branch.assert_called_once_with("release/0.0")

        # Should create and push tag
        mock_git_instance.create_tag.assert_called_once()
        mock_git_instance.push_tag.assert_called_once_with("v0.0.1-rc.0")

        # Should succeed
        assert result.exit_code == 0


def test_branch_creation_not_called_when_exists(test_config, test_notes_file):
    """Test that branch creation is skipped when branch already exists."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_gh_client, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class:

        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None  # No existing repo/release

        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []
        mock_git_instance.tag_exists.return_value = False  # Tag doesn't exist

        # Mock strategy to return should_create_branch=False (branch exists)
        mock_strategy.return_value = ("release/0.0", "main", False)

        # Mock GitHub client
        mock_gh_instance = MagicMock()
        mock_gh_client.return_value = mock_gh_instance
        mock_gh_instance.get_release_by_tag.return_value = None  # No existing release
        mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v0.0.1"

        result = runner.invoke(
            publish,
            ['0.0.1', '-f', str(test_notes_file), '--release'],
            obj={'config': test_config}
        )

        # Should NOT call create_branch or push_branch
        mock_git_instance.create_branch.assert_not_called()
        mock_git_instance.push_branch.assert_not_called()

        # Should still create and push tag
        mock_git_instance.create_tag.assert_called_once()
        mock_git_instance.push_tag.assert_called_once_with("v0.0.1")

        # Should succeed
        assert result.exit_code == 0


def test_branch_creation_in_dry_run(test_config, test_notes_file):
    """Test that dry-run shows branch creation without actually creating it."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class:

        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None  # No existing repo/release

        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []

        # Mock strategy to return should_create_branch=True
        mock_strategy.return_value = ("release/0.0", "main", True)

        result = runner.invoke(
            publish,
            ['0.0.1-rc.0', '-f', str(test_notes_file), '--dry-run', '--release'],
            obj={'config': test_config}
        )

        # Should NOT actually call create_branch or push_branch in dry-run
        mock_git_instance.create_branch.assert_not_called()
        mock_git_instance.push_branch.assert_not_called()

        # Should show dry run output with target branch
        assert 'DRY RUN' in result.output
        assert 'Target: release/0.0' in result.output
        # Should succeed
        assert result.exit_code == 0


def test_branch_creation_error_handling(test_config, test_notes_file):
    """Test that branch creation errors are handled gracefully."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_gh_client, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class:

        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None  # No existing repo/release

        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []
        mock_git_instance.tag_exists.return_value = False  # Tag doesn't exist
        mock_git_instance.branch_exists.return_value = False  # Branch doesn't exist (neither local nor remote)

        # Mock strategy to return should_create_branch=True
        mock_strategy.return_value = ("release/0.0", "main", True)

        # Make create_branch raise an exception
        mock_git_instance.create_branch.side_effect = Exception("Branch creation failed")

        # Mock GitHub client
        mock_gh_instance = MagicMock()
        mock_gh_client.return_value = mock_gh_instance
        mock_gh_instance.get_release_by_tag.return_value = None  # No existing release
        mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v0.0.1-rc.0"

        result = runner.invoke(
            publish,
            ['0.0.1-rc.0', '-f', str(test_notes_file), '--release'],
            obj={'config': test_config}
        )

        # Should show warning about branch creation failure
        assert 'Warning: Could not create/push release branch' in result.output
        assert 'Continuing with release creation' in result.output

        # Should still proceed with release creation (exit code 0)
        assert result.exit_code == 0
def test_branch_creation_disabled_by_config(test_config, test_notes_file):
    """Test that branch creation is skipped when disabled in config."""
    # Modify config to disable branch creation
    test_config.branch_policy.create_branches = False

    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_gh_client, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class:

        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None  # No existing repo/release

        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []
        mock_git_instance.tag_exists.return_value = False  # Tag doesn't exist

        # Mock strategy to return should_create_branch=True
        mock_strategy.return_value = ("release/0.0", "main", True)

        # Mock GitHub client
        mock_gh_instance = MagicMock()
        mock_gh_client.return_value = mock_gh_instance
        mock_gh_instance.get_release_by_tag.return_value = None  # No existing release
        mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v0.0.1-rc.0"

        result = runner.invoke(
            publish,
            ['0.0.1-rc.0', '-f', str(test_notes_file), '--release'],
            obj={'config': test_config}
        )

        # Should NOT call create_branch or push_branch when disabled in config
        mock_git_instance.create_branch.assert_not_called()
        mock_git_instance.push_branch.assert_not_called()

        # Should still create and push tag
        mock_git_instance.create_tag.assert_called_once()
        mock_git_instance.push_tag.assert_called_once_with("v0.0.1-rc.0")

        # Should succeed (but will likely fail at GitHub release creation due to missing branch)
        # For this test we're just verifying branch creation was skipped
        assert result.exit_code == 0


def test_ticket_parameter_associates_with_issue(test_config, test_notes_file):
    """Test that --ticket parameter properly associates release with a GitHub issue."""
    runner = CliRunner()
    
    with patch('release_tool.commands.publish.GitHubClient') as mock_gh_client, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class:
        
        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None
        mock_db.get_ticket_association.return_value = None  # No existing association
        
        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.branch_exists.return_value = True
        
        # Mock strategy
        mock_strategy.return_value = ("release/0.0", "main", False)
        
        # Mock GitHub client
        mock_gh_instance = MagicMock()
        mock_gh_client.return_value = mock_gh_instance
        mock_gh_instance.get_release_by_tag.return_value = None  # No existing release
        mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v0.0.1"
        
        # Mock the issue retrieval
        mock_issue = MagicMock()
        mock_issue.number = 123
        mock_issue.html_url = "https://github.com/test/repo/issues/123"
        mock_gh_instance.gh.get_repo.return_value.get_issue.return_value = mock_issue
        
        # Enable ticket creation and PR creation in config
        test_config.output.create_ticket = True
        test_config.output.create_pr = True
        
        result = runner.invoke(
            publish,
            ['0.0.1', '-f', str(test_notes_file), '--release', '--pr', '--ticket', '123'],
            obj={'config': test_config}
        )
        
        assert result.exit_code == 0
        
        # Verify the issue was retrieved (can be called multiple times during PR creation)
        mock_gh_instance.gh.get_repo.return_value.get_issue.assert_called_with(123)
        
        # Verify the ticket association was saved to database
        assert mock_db.save_ticket_association.called
        # Find the call with ticket_number=123
        calls = [call for call in mock_db.save_ticket_association.call_args_list 
                 if 'ticket_number' in call[1] and call[1]['ticket_number'] == 123]
        assert len(calls) > 0
        call_args = calls[0]
        assert call_args[1]['version'] == '0.0.1'
        assert call_args[1]['ticket_url'] == "https://github.com/test/repo/issues/123"


def test_auto_select_open_ticket_for_draft_release(test_config, test_notes_file):
    """Test that publishing with --force draft auto-selects the first open ticket."""
    runner = CliRunner()
    
    with patch('release_tool.commands.publish.GitHubClient') as mock_gh_client, \
         patch('release_tool.commands.publish.GitOperations') as mock_git_ops, \
         patch('release_tool.commands.publish.determine_release_branch_strategy') as mock_strategy, \
         patch('release_tool.commands.publish.Database') as mock_db_class, \
         patch('release_tool.commands.publish._find_existing_ticket_auto') as mock_find_ticket:
        
        # Mock database
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_db.get_repository.return_value = None
        mock_db.get_ticket_association.return_value = None  # No existing association
        
        # Mock git operations
        mock_git_instance = MagicMock()
        mock_git_ops.return_value = mock_git_instance
        mock_git_instance.get_version_tags.return_value = []
        mock_git_instance.tag_exists.return_value = False
        mock_git_instance.branch_exists.return_value = True
        
        # Mock strategy
        mock_strategy.return_value = ("release/0.0", "main", False)
        
        # Mock GitHub client
        mock_gh_instance = MagicMock()
        mock_gh_client.return_value = mock_gh_instance
        mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v0.0.1-rc.0"
        
        # Mock automatic ticket finding (returns first open ticket)
        mock_find_ticket.return_value = {
            'number': '456',
            'url': 'https://github.com/test/repo/issues/456'
        }
        
        # Enable ticket creation and PR creation in config
        test_config.output.create_ticket = True
        test_config.output.create_pr = True
        
        result = runner.invoke(
            publish,
            ['0.0.1-rc.0', '-f', str(test_notes_file), '--release', '--pr', '--force', 'draft'],
            obj={'config': test_config}
        )
        
        assert result.exit_code == 0
        
        # Verify auto-selection was called
        mock_find_ticket.assert_called_once()
        
        # Verify the ticket association was saved
        mock_db.save_ticket_association.assert_called()
        call_args = mock_db.save_ticket_association.call_args
        assert call_args[1]['ticket_number'] == 456
        assert call_args[1]['version'] == '0.0.1-rc.0'


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_existing_release_without_force_errors(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test that publishing fails when release exists and --force is not set."""
    runner = CliRunner()
    
    # Mock database
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_db_instance.get_repository.return_value = mock_repo
    mock_db_instance.get_release.return_value = None  # No DB release yet
    
    # Mock git operations
    mock_git_instance = MagicMock()
    mock_git_ops.return_value = mock_git_instance
    mock_git_instance.get_version_tags.return_value = []
    mock_git_instance.tag_exists.return_value = True  # Tag already exists
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - existing release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    # Mock existing release
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0"
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release'],
        obj={'config': test_config}
    )
    
    # Should fail with error
    assert result.exit_code == 1
    assert 'already exists' in result.output
    assert 'Use --force' in result.output


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_existing_release_with_force_updates(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test that publishing updates existing release when --force is set."""
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
    mock_git_instance.tag_exists.return_value = True
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    # Mock existing release
    mock_existing_release = MagicMock()
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/v1.0.0"
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--force', 'published'],
        obj={'config': test_config}
    )
    
    # Should succeed
    assert result.exit_code == 0
    assert 'Updating existing' in result.output or 'updated successfully' in result.output
    
    # Verify update_release was called
    mock_gh_instance.update_release.assert_called_once()
    call_args = mock_gh_instance.update_release.call_args
    assert call_args[0][0] == 'test/repo'
    assert call_args[0][1] == 'v1.0.0'


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_new_release_without_force_creates(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test that publishing creates new release when it doesn't exist."""
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
    mock_git_instance.tag_exists.return_value = False
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client - no existing release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    mock_gh_instance.get_release_by_tag.return_value = None  # No existing release
    mock_gh_instance.create_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release'],
        obj={'config': test_config}
    )
    
    # Should succeed
    assert result.exit_code == 0
    assert 'created successfully' in result.output
    
    # Verify create_release was called (not update)
    mock_gh_instance.create_release.assert_called_once()
    mock_gh_instance.update_release.assert_not_called()


@patch('release_tool.commands.publish.Database')
@patch('release_tool.commands.publish.GitOperations')
@patch('release_tool.commands.publish.determine_release_branch_strategy')
@patch('release_tool.commands.publish.GitHubClient')
def test_existing_untagged_release_with_force_updates(mock_gh_client, mock_strategy, mock_git_ops, mock_db, test_config, test_notes_file):
    """Test that publishing updates existing 'untagged' release when --force is set."""
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
    mock_git_instance.tag_exists.return_value = True
    mock_git_instance.branch_exists.return_value = True
    
    # Mock strategy
    mock_strategy.return_value = ("release/1.0", "main", False)
    
    # Mock GitHub client with an "untagged" release
    mock_gh_instance = MagicMock()
    mock_gh_client.return_value = mock_gh_instance
    
    # Mock existing untagged release
    mock_existing_release = MagicMock()
    mock_existing_release.tag_name = "untagged-6ebfa1379a96e20ddfc1"
    mock_existing_release.title = "Release 1.0.0"
    mock_existing_release.html_url = "https://github.com/test/repo/releases/tag/untagged-6ebfa1379a96e20ddfc1"
    mock_gh_instance.get_release_by_tag.return_value = mock_existing_release
    mock_gh_instance.update_release.return_value = "https://github.com/test/repo/releases/tag/v1.0.0"
    
    result = runner.invoke(
        publish,
        ['1.0.0', '-f', str(test_notes_file), '--release', '--force', 'published'],
        obj={'config': test_config}
    )
    
    # Should succeed
    assert result.exit_code == 0
    assert 'Updating existing' in result.output or 'updated successfully' in result.output
    
    # Verify update_release was called (not create)
    mock_gh_instance.update_release.assert_called_once()
    mock_gh_instance.create_release.assert_not_called()
