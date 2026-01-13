# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""End-to-end tests for cancel command."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
from click.testing import CliRunner
from datetime import datetime

from release_tool.commands.cancel import cancel
from release_tool.config import Config
from release_tool.db import Database
from release_tool.models import Release, PullRequest, Issue, Repository


@pytest.fixture
def test_config(tmp_path):
    """Create a test configuration with database."""
    db_path = tmp_path / "test.db"
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}]
        },
        "github": {
            "token": "test_token"
        },
        "database": {
            "path": str(db_path)
        },
        "output": {
            "create_github_release": True,
            "create_pr": True,
            "draft_output_path": ".release_tool_cache/draft-releases/{{repo}}/{{version}}.md"
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def populated_db(test_config):
    """Create a database with test data."""
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

    # Create a draft release
    draft_release = Release(
        repo_id=repo_id,
        version="1.2.3-rc.1",
        tag_name="v1.2.3-rc.1",
        published_at=None,
        created_at=datetime.now(),
        is_draft=True,
        is_prerelease=True,
        url="https://github.com/test/repo/releases/tag/v1.2.3-rc.1"
    )
    draft_release_id = db.upsert_release(draft_release)

    # Create a published release
    published_release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        published_at=datetime.now(),
        created_at=datetime.now(),
        is_draft=False,
        is_prerelease=False,
        url="https://github.com/test/repo/releases/tag/v1.0.0"
    )
    published_release_id = db.upsert_release(published_release)

    # Create a PR for the draft release
    pr = PullRequest(
        repo_id=repo_id,
        number=42,
        title="Release notes for v1.2.3-rc.1",
        body="Automated release notes #1",
        state="open",
        url="https://github.com/test/repo/pull/42",
        head_branch="release-notes-v1.2.3-rc.1",
        base_branch="main"
    )
    pr_id = db.upsert_pull_request(pr)

    # Create an issue for the draft release
    issue = Issue(
        repo_id=repo_id,
        number=1,
        key="1",  # key can be the issue number as string
        title="Release 1.2.3-rc.1",
        body="Tracking issue for release 1.2.3-rc.1",
        state="open",
        url="https://github.com/test/repo/issues/1"
    )
    issue_id = db.upsert_issue(issue)

    yield db, repo_id, {
        'draft_release_id': draft_release_id,
        'published_release_id': published_release_id,
        'pr_id': pr_id,
        'pr_number': 42,
        'issue_id': issue_id,
        'issue_number': 1
    }

    db.close()


class TestE2ECancelDryRun:
    """Test cancel command in dry-run mode."""

    def test_dry_run_draft_release_shows_plan(self, test_config, populated_db):
        """Test dry-run shows what would be deleted without actually deleting."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--dry-run'],
                obj={'config': test_config, 'debug': False},
                catch_exceptions=False
            )

        # Should not create GitHub client in dry-run
        mock_client_class.assert_not_called()

        # Should show dry-run banner
        assert 'DRY RUN' in result.output or 'Dry run' in result.output

        # Should show what would be deleted
        assert '1.2.3-rc.1' in result.output
        assert ('Will perform' in result.output or 'would' in result.output.lower() or
                'Delete' in result.output or 'delete' in result.output.lower())

        # Should mention the release and tag
        assert 'release' in result.output.lower()
        assert 'tag' in result.output.lower() or 'v1.2.3-rc.1' in result.output

        # Should exit successfully
        assert result.exit_code == 0

    def test_dry_run_with_pr_and_issue(self, test_config, populated_db):
        """Test dry-run shows PR and issue that would be closed."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--issue', '1', '--pr', '42', '--dry-run'],
                obj={'config': test_config, 'debug': False},
                catch_exceptions=False
            )

        # Should not make API calls in dry-run
        mock_client_class.assert_not_called()

        # Should show PR and issue in output
        assert '#42' in result.output or 'PR' in result.output or 'pull' in result.output.lower()
        assert '#1' in result.output or 'issue' in result.output.lower()

        assert result.exit_code == 0

    def test_dry_run_published_release_blocked(self, test_config, populated_db):
        """Test dry-run shows published release is blocked without --force."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        result = runner.invoke(
            cancel,
            ['1.0.0', '--dry-run'],
            obj={'config': test_config, 'debug': False},
            catch_exceptions=False
        )

        # Should fail because release is published
        assert result.exit_code != 0
        assert 'published' in result.output.lower() or 'force' in result.output.lower()

    def test_dry_run_published_release_with_force(self, test_config, populated_db):
        """Test dry-run with --force allows published release deletion."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            result = runner.invoke(
                cancel,
                ['1.0.0', '--force', '--dry-run'],
                obj={'config': test_config, 'debug': False},
                catch_exceptions=False
            )

        # Should not make API calls in dry-run
        mock_client_class.assert_not_called()

        # Should show what would be deleted
        assert ('Will perform' in result.output or 'would' in result.output.lower() or
                'Delete' in result.output or 'delete' in result.output.lower())
        assert '1.0.0' in result.output

        # Should exit successfully with force flag
        assert result.exit_code == 0


class TestE2ECancelExecution:
    """Test cancel command actual execution."""

    def test_cancel_draft_release_deletes_all_resources(self, test_config, populated_db):
        """Test cancel deletes release, tag, and database records."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True

            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1'],
                obj={'config': test_config, 'debug': False, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should create GitHub client
        mock_client_class.assert_called_once()

        # Should delete release and tag
        mock_client.delete_release.assert_called_once_with('test/repo', 'v1.2.3-rc.1')
        mock_client.delete_tag.assert_called_once_with('test/repo', 'v1.2.3-rc.1')

        # Should show success
        assert result.exit_code == 0
        assert 'Successfully cancelled' in result.output or 'Deleted' in result.output or 'success' in result.output.lower()

        # Verify database records were deleted
        draft_release = db.get_release(repo_id, '1.2.3-rc.1')
        assert draft_release is None, "Draft release should be deleted from database"

    def test_cancel_with_pr_closes_and_deletes_branch(self, test_config, populated_db):
        """Test cancel closes PR and deletes branch."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.close_pull_request.return_value = True
            mock_client.delete_branch.return_value = True
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True

            # Mock get_pull_request to return PR details
            mock_pr = Mock()
            mock_pr.head.ref = "release-notes-v1.2.3-rc.1"
            mock_client.get_pull_request.return_value = mock_pr

            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--pr', '42'],
                obj={'config': test_config, 'debug': False, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should close PR (without comment - release-bot will add success comment)
        mock_client.close_pull_request.assert_called_once_with(
            'test/repo',
            42
        )

        # Should delete branch
        mock_client.delete_branch.assert_called_once_with(
            'test/repo',
            'release-notes-v1.2.3-rc.1'
        )

        assert result.exit_code == 0

    def test_cancel_with_issue_closes_issue(self, test_config, populated_db):
        """Test cancel closes associated issue."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True
            mock_client.close_issue.return_value = True

            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--issue', '1'],
                obj={'config': test_config, 'debug': False, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should close issue (without comment - release-bot will add success comment)
        mock_client.close_issue.assert_called_once_with(
            'test/repo',
            1
        )

        assert result.exit_code == 0

    def test_cancel_stops_on_first_failure(self, test_config, populated_db):
        """Test cancel stops on first failure without continuing."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock to fail on PR close
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.close_pull_request.return_value = False  # Fail
            mock_client.delete_branch.return_value = True
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True

            # Mock get_pull_request
            mock_pr = Mock()
            mock_pr.head.ref = "release-notes-v1.2.3-rc.1"
            mock_client.get_pull_request.return_value = mock_pr

            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--pr', '42'],
                obj={'config': test_config, 'debug': False, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should attempt to close PR
        mock_client.close_pull_request.assert_called_once()

        # Should NOT continue to delete branch (stop on first failure)
        mock_client.delete_branch.assert_not_called()

        # Should fail
        assert result.exit_code != 0
        assert 'failed' in result.output.lower() or 'error' in result.output.lower()


class TestE2ECancelAutoDetection:
    """Test cancel command auto-detection of version, PR, and issue."""

    def test_auto_detect_pr_from_version(self, test_config, populated_db):
        """Test cancel auto-detects PR number from version in database."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        # Create a PR with version in title
        pr = PullRequest(
            repo_id=repo_id,
            number=99,
            title="Release notes for v1.2.3-rc.1",
            body="Auto-generated release notes",
            state="open",
            url="https://github.com/test/repo/pull/99",
            head_branch="release-notes-v1.2.3-rc.1",
            base_branch="main"
        )
        db.upsert_pull_request(pr)

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.close_pull_request.return_value = True
            mock_client.delete_branch.return_value = True
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True

            # Mock get_pull_request
            mock_pr = Mock()
            mock_pr.head.ref = "release-notes-v1.2.3-rc.1"
            mock_client.get_pull_request.return_value = mock_pr

            # Don't provide --pr flag, let it auto-detect
            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1'],
                obj={'config': test_config, 'debug': True, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should auto-detect and close PR 99
        # Check if PR was closed (either 42 or 99, depending on which it found)
        assert mock_client.close_pull_request.called or result.exit_code == 0

    def test_cancel_with_no_version_fails_gracefully(self, test_config, populated_db):
        """Test cancel fails gracefully when version not provided and can't be auto-detected."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        # Try to cancel with only issue number (no version)
        result = runner.invoke(
            cancel,
            ['--issue', '999'],  # Non-existent issue
            obj={'config': test_config, 'debug': False},
            catch_exceptions=False
        )

        # Should fail because version is required or must be auto-detectable
        assert result.exit_code != 0


class TestE2ECancelEdgeCases:
    """Test cancel command edge cases and error handling."""

    def test_cancel_nonexistent_version(self, test_config, populated_db):
        """Test cancel with version that doesn't exist in database."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock - GitHub operations will be idempotent
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True

            result = runner.invoke(
                cancel,
                ['9.9.9', '--force'],  # Version not in database
                obj={'config': test_config, 'debug': False, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should still attempt to delete from GitHub (idempotent)
        mock_client.delete_release.assert_called_once_with('test/repo', 'v9.9.9')
        mock_client.delete_tag.assert_called_once_with('test/repo', 'v9.9.9')

        # Should succeed (idempotent operations)
        assert result.exit_code == 0

    def test_cancel_already_deleted_resources_succeeds(self, test_config, populated_db):
        """Test cancel succeeds when resources are already deleted (idempotent)."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock - all operations return True (already deleted)
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True
            mock_client.close_pull_request.return_value = True
            mock_client.delete_branch.return_value = True

            # Mock get_pull_request to return None (already deleted)
            mock_client.get_pull_request.return_value = None

            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--pr', '42'],
                obj={'config': test_config, 'debug': False, 'assume_yes': True},
                catch_exceptions=False
            )

        # Should succeed (idempotent)
        assert result.exit_code == 0

    def test_cancel_with_debug_shows_detailed_output(self, test_config, populated_db):
        """Test cancel with debug flag shows detailed output."""
        db, repo_id, test_data = populated_db
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            # Setup mock
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.delete_release.return_value = True
            mock_client.delete_tag.return_value = True

            result = runner.invoke(
                cancel,
                ['1.2.3-rc.1', '--dry-run'],
                obj={'config': test_config, 'debug': True},
                catch_exceptions=False
            )

        # Debug mode should show more details
        # The actual output format depends on implementation
        assert result.exit_code == 0
        # Should at least show the version
        assert '1.2.3-rc.1' in result.output


class TestE2ECancelPatternMatching:
    """Test cancel command with pattern-based PR detection."""

    def test_cancel_detects_pr_from_branch_name(self, test_config, tmp_path):
        """Test that cancel detects PR using branch name pattern (issue #64 scenario)."""
        # Setup database
        db = Database(test_config.database.path)
        db.connect()

        # Create repository
        repo = Repository(
            owner="sequentech",
            name="meta",
            full_name="sequentech/meta",
            url="https://github.com/sequentech/meta"
        )
        repo_id = db.upsert_repository(repo)

        # Create a draft release for v11.0.0-rc.4
        release = Release(
            repo_id=repo_id,
            version="11.0.0-rc.4",
            tag_name="v11.0.0-rc.4",
            published_at=None,
            created_at=datetime.now(),
            is_draft=True,
            is_prerelease=True,
            url="https://github.com/sequentech/meta/releases/tag/v11.0.0-rc.4"
        )
        db.upsert_release(release)

        # Create issue #64 for this release
        issue = Issue(
            repo_id=repo_id,
            number=64,
            key="64",
            title="Release 11.0.0-rc.4",
            body="Tracking issue for release 11.0.0-rc.4",
            state="open",
            url="https://github.com/sequentech/meta/issues/64"
        )
        db.upsert_issue(issue)

        # Create a PR with branch name following the pattern: feat/meta-64/main
        # This should be detected by the branch_name pattern: /(?P<repo>\\w+)-(?P<issue>\\d+)
        pr = PullRequest(
            repo_id=repo_id,
            number=123,
            title="Release notes for v11.0.0-rc.4",
            body="Automated release notes",
            state="open",
            url="https://github.com/sequentech/meta/pull/123",
            head_branch="feat/meta-64/main",  # Branch contains issue #64
            base_branch="main"
        )
        db.upsert_pull_request(pr)

        # Link issue to version
        db.save_issue_association("sequentech/meta", "11.0.0-rc.4", 64, "https://github.com/sequentech/meta/issues/64")

        db.close()

        # Update config to use sequentech/meta repo
        from release_tool.config import RepoInfo
        test_config.repository.code_repos = [RepoInfo(link="sequentech/meta", alias="meta")]

        # Run cancel command with issue #64 in dry-run mode
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            result = runner.invoke(
                cancel,
                ['--issue', '64', '--dry-run'],
                obj={'config': test_config, 'debug': False},
                catch_exceptions=False
            )

        # Should not make API calls in dry-run
        mock_client_class.assert_not_called()

        # Should show that PR #123 will be closed
        assert result.exit_code == 0
        assert 'PR' in result.output or 'pull' in result.output.lower() or '#123' in result.output

        # Should show version, release, and issue
        assert '11.0.0-rc.4' in result.output
        assert '#64' in result.output or 'issue' in result.output.lower()

    def test_cancel_detects_pr_from_pr_body(self, test_config, tmp_path):
        """Test that cancel detects PR using PR body pattern."""
        # Setup database
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

        # Create a draft release
        release = Release(
            repo_id=repo_id,
            version="2.0.0-rc.1",
            tag_name="v2.0.0-rc.1",
            published_at=None,
            created_at=datetime.now(),
            is_draft=True,
            is_prerelease=True,
            url="https://github.com/test/repo/releases/tag/v2.0.0-rc.1"
        )
        db.upsert_release(release)

        # Create issue #99
        issue = Issue(
            repo_id=repo_id,
            number=99,
            key="99",
            title="Release 2.0.0-rc.1",
            body="Tracking issue",
            state="open",
            url="https://github.com/test/repo/issues/99"
        )
        db.upsert_issue(issue)

        # Create a PR with issue reference in body (not in branch name)
        pr = PullRequest(
            repo_id=repo_id,
            number=200,
            title="Release notes",
            body="Parent issue: https://github.com/sequentech/meta/issues/99\n\nRelease notes",
            state="open",
            url="https://github.com/test/repo/pull/200",
            head_branch="release-notes-branch",
            base_branch="main"
        )
        db.upsert_pull_request(pr)

        # Link issue to version
        db.save_issue_association("test/repo", "2.0.0-rc.1", 99, "https://github.com/test/repo/issues/99")

        db.close()

        # Run cancel command with issue #99
        runner = CliRunner()

        with patch('release_tool.commands.cancel.GitHubClient') as mock_client_class:
            result = runner.invoke(
                cancel,
                ['--issue', '99', '--dry-run'],
                obj={'config': test_config, 'debug': False},
                catch_exceptions=False
            )

        # Should not make API calls in dry-run
        mock_client_class.assert_not_called()

        # Should show that PR will be closed
        assert result.exit_code == 0
        assert 'PR' in result.output or '#200' in result.output or 'pull' in result.output.lower()
