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
            "prerelease": False
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
        ['1.0.0-rc.1', '-f', str(test_notes_file), '--dry-run', '--release', '--draft', '--prerelease'],
        obj={'config': test_config}
    )

    assert 'DRY RUN' in result.output
    assert 'Draft' in result.output or 'draft' in result.output
    assert result.exit_code == 0


def test_config_defaults_used_when_no_cli_flags(test_config, test_notes_file):
    """Test that config defaults are used when CLI flags are not provided."""
    # Set config defaults
    test_config.output.create_github_release = True
    test_config.output.draft_release = True

    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client

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

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client

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
            ['1.0.0', '-f', str(test_notes_file), '--debug', '--dry-run'],
            obj={'config': test_config}
        )

        # Should show debug output
        assert 'Debug:' in result.output
        assert 'Configuration values' in result.output
        assert 'Parsed version' in result.output
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
        ['1.0.0', '-f', str(test_notes_file), '--debug', '--dry-run'],
        obj={'config': test_config}
    )

    # Should show doc file info in debug mode
    assert 'Docusaurus' in result.output
    assert str(doc_file) in result.output
    assert 'Docusaurus notes preview' in result.output or 'Docusaurus file length' in result.output
    assert result.exit_code == 0


def test_error_handling_with_debug(test_config, test_notes_file):
    """Test that debug mode re-raises exceptions with stack trace."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.SemanticVersion.parse', side_effect=Exception("Test error")):
        result = runner.invoke(
            publish,
            ['invalid', '-f', str(test_notes_file), '--debug'],
            obj={'config': test_config}
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
    """Test that prerelease is auto-detected from version."""
    runner = CliRunner()

    with patch('release_tool.commands.publish.GitHubClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client

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
    assert str(doc_file) in result.output
    assert 'File exists' in result.output
    assert result.exit_code == 0


def test_pr_requires_notes_file(test_config):
    """Test that creating PR requires notes file."""
    runner = CliRunner()

    result = runner.invoke(
        publish,
        ['1.0.0', '--pr'],
        obj={'config': test_config}
    )

    # Should error about missing notes file
    assert '--notes-file required' in result.output
    assert result.exit_code == 0  # Currently returns, not exit(1)
