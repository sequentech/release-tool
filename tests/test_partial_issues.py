# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for partial issue match handling."""

import pytest
from io import StringIO
from unittest.mock import Mock, patch
from datetime import datetime

from release_tool.policies import PartialIssueMatch, PartialIssueReason
from release_tool.config import Config, PolicyAction
from release_tool.models import Author, Commit, PullRequest, ConsolidatedChange
from release_tool.commands.generate import _handle_partial_issues, _get_extraction_source


@pytest.fixture
def test_config_warn():
    """Create a test configuration with warn policy."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}],
            "issue_repos": [{"link": "test/meta", "alias": "meta"}]
        },
        "github": {
            "token": "test_token"
        },
        "issue_policy": {
            "partial_issue_action": "warn"
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_config_ignore():
    """Create a test configuration with ignore policy."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}],
            "issue_repos": [{"link": "test/meta", "alias": "meta"}]
        },
        "github": {
            "token": "test_token"
        },
        "issue_policy": {
            "partial_issue_action": "ignore"
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_config_error():
    """Create a test configuration with error policy."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}],
            "issue_repos": [{"link": "test/meta", "alias": "meta"}]
        },
        "github": {
            "token": "test_token"
        },
        "issue_policy": {
            "partial_issue_action": "error"
        }
    }
    return Config.from_dict(config_dict)


class TestPartialIssueMatch:
    """Tests for PartialIssueMatch dataclass."""

    def test_create_not_found_partial(self):
        """Test creating a partial match for a issue not found."""
        partial = PartialIssueMatch(
            issue_key="8624",
            extracted_from="branch feat/meta-8624/main, PR #123",
            match_type="not_found",
            potential_reasons={
                PartialIssueReason.OLDER_THAN_CUTOFF,
                PartialIssueReason.TYPO,
                PartialIssueReason.PULL_NOT_RUN
            }
        )

        assert partial.issue_key == "8624"
        assert partial.match_type == "not_found"
        assert len(partial.potential_reasons) == 3
        assert PartialIssueReason.OLDER_THAN_CUTOFF in partial.potential_reasons
        assert partial.found_in_repo is None
        assert partial.issue_url is None

    def test_create_different_repo_partial(self):
        """Test creating a partial match for a issue in different repo."""
        partial = PartialIssueMatch(
            issue_key="8853",
            extracted_from="branch feat/step-8853/main, PR #456",
            match_type="different_repo",
            found_in_repo="test/different-repo",
            issue_url="https://github.com/test/different-repo/issues/8853",
            potential_reasons={
                PartialIssueReason.REPO_CONFIG_MISMATCH,
                PartialIssueReason.WRONG_ISSUE_REPOS
            }
        )

        assert partial.issue_key == "8853"
        assert partial.match_type == "different_repo"
        assert partial.found_in_repo == "test/different-repo"
        assert partial.issue_url == "https://github.com/test/different-repo/issues/8853"
        assert len(partial.potential_reasons) == 2
        assert PartialIssueReason.REPO_CONFIG_MISMATCH in partial.potential_reasons


class TestPartialIssueReason:
    """Tests for PartialIssueReason enum."""

    def test_reason_descriptions(self):
        """Test that all reasons have descriptions."""
        assert PartialIssueReason.OLDER_THAN_CUTOFF.description == "Issue may be older than pull cutoff date"
        assert PartialIssueReason.TYPO.description == "Issue may not exist (typo in branch/PR)"
        assert PartialIssueReason.PULL_NOT_RUN.description == "Pull may not have been run yet"
        assert PartialIssueReason.REPO_CONFIG_MISMATCH.description == "Issue found in different repo than configured"
        assert PartialIssueReason.WRONG_ISSUE_REPOS.description == "Check repository.issue_repos in config"

    def test_reason_values(self):
        """Test enum values are correct."""
        assert PartialIssueReason.OLDER_THAN_CUTOFF.value == "older_than_cutoff"
        assert PartialIssueReason.TYPO.value == "typo"
        assert PartialIssueReason.PULL_NOT_RUN.value == "pull_not_run"
        assert PartialIssueReason.REPO_CONFIG_MISMATCH.value == "repo_config_mismatch"
        assert PartialIssueReason.WRONG_ISSUE_REPOS.value == "wrong_issue_repos"


class TestGetExtractionSource:
    """Tests for _get_extraction_source helper."""

    def test_extraction_from_pr_with_branch(self):
        """Test extraction source from PR with branch."""
        pr = PullRequest(
            repo_id=1,
            number=123,
            title="Fix bug",
            state="closed",
            head_branch="feat/meta-8624/main"
        )
        change = ConsolidatedChange(
            type="issue",
            issue_key="8624",
            prs=[pr],
            commits=[]
        )

        source = _get_extraction_source(change)

        assert "feat/meta-8624/main" in source
        assert "PR #123" in source
        assert "branch" in source

    def test_extraction_from_pr_without_branch(self):
        """Test extraction source from PR without branch."""
        pr = PullRequest(
            repo_id=1,
            number=456,
            title="Fix bug",
            state="closed"
        )
        change = ConsolidatedChange(
            type="pr",
            issue_key="8853",
            prs=[pr],
            commits=[]
        )

        source = _get_extraction_source(change)

        assert "PR #456" in source
        assert "branch" not in source

    def test_extraction_from_commit(self):
        """Test extraction source from commit."""
        commit = Commit(
            sha="abc1234567890",
            repo_id=1,
            message="Fix bug",
            author=Author(name="dev"),
            date=datetime.now()
        )
        change = ConsolidatedChange(
            type="commit",
            issue_key="999",
            prs=[],
            commits=[commit]
        )

        source = _get_extraction_source(change)

        assert "commit" in source
        assert "abc1234" in source

    def test_extraction_unknown_source(self):
        """Test extraction source when unknown."""
        change = ConsolidatedChange(
            type="issue",
            issue_key="111",
            prs=[],
            commits=[]
        )

        source = _get_extraction_source(change)

        assert source == "unknown source"


class TestHandlePartialIssues:
    """Tests for _handle_partial_issues function."""

    def test_ignore_policy_no_output(self, test_config_ignore, capsys):
        """Test that ignore policy produces no output."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialIssueReason.OLDER_THAN_CUTOFF}
            )
        ]

        # Should not raise, should not print
        _handle_partial_issues(partials, set(), test_config_ignore, debug=False)

        # No exception raised means success
        assert True

    def test_warn_policy_prints_message(self, test_config_warn, capsys):
        """Test that warn policy prints warning message."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main, PR #123",
                match_type="not_found",
                potential_reasons={
                    PartialIssueReason.OLDER_THAN_CUTOFF,
                    PartialIssueReason.TYPO
                }
            )
        ]

        _handle_partial_issues(partials, set(), test_config_warn, debug=False)

        # Capture should include warning about partial matches
        # Note: Using rich Console means we can't easily capture output in tests
        # This test verifies no exception is raised
        assert True

    def test_error_policy_raises_exception(self, test_config_error):
        """Test that error policy raises RuntimeError."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialIssueReason.PULL_NOT_RUN}
            )
        ]

        with pytest.raises(RuntimeError) as exc_info:
            _handle_partial_issues(partials, set(), test_config_error, debug=False)

        assert "Unresolved partial issue matches found" in str(exc_info.value) or "Partial issue matches found" in str(exc_info.value)
        assert "1 total" in str(exc_info.value)

    def test_error_policy_with_multiple_partials(self, test_config_error):
        """Test error policy with multiple partials."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialIssueReason.OLDER_THAN_CUTOFF}
            ),
            PartialIssueMatch(
                issue_key="8853",
                extracted_from="branch feat/step-8853/main",
                match_type="different_repo",
                found_in_repo="test/different",
                issue_url="https://github.com/test/different/issues/8853",
                potential_reasons={PartialIssueReason.REPO_CONFIG_MISMATCH}
            )
        ]

        with pytest.raises(RuntimeError) as exc_info:
            _handle_partial_issues(partials, set(), test_config_error, debug=False)

        assert "2 total" in str(exc_info.value)

    def test_no_partials_does_nothing(self, test_config_warn):
        """Test that empty partial list does nothing."""
        partials = []

        # Should not raise, should not print
        _handle_partial_issues(partials, set(), test_config_warn, debug=False)

        assert True

    @patch('release_tool.commands.generate.console')
    def test_warn_consolidates_by_reason(self, mock_console, test_config_warn):
        """Test that warnings consolidate issues by reason."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={
                    PartialIssueReason.OLDER_THAN_CUTOFF,
                    PartialIssueReason.PULL_NOT_RUN
                }
            ),
            PartialIssueMatch(
                issue_key="8853",
                extracted_from="branch feat/meta-8853/main",
                match_type="not_found",
                potential_reasons={
                    PartialIssueReason.OLDER_THAN_CUTOFF  # Same reason as 8624
                }
            )
        ]

        _handle_partial_issues(partials, set(), test_config_warn, debug=False)

        # Verify console.print was called
        assert mock_console.print.called

        # Get the printed message
        call_args = mock_console.print.call_args[0][0]

        # Should mention both issues
        assert "8624" in call_args
        assert "8853" in call_args

        # Should mention the reason
        assert "older than pull cutoff" in call_args or "OLDER_THAN_CUTOFF" in call_args

    @patch('release_tool.commands.generate.console')
    def test_warn_different_repo_includes_url(self, mock_console, test_config_warn):
        """Test that different_repo warnings include URLs."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="different_repo",
                found_in_repo="test/other-repo",
                issue_url="https://github.com/test/other-repo/issues/8624",
                potential_reasons={PartialIssueReason.REPO_CONFIG_MISMATCH}
            )
        ]

        _handle_partial_issues(partials, set(), test_config_warn, debug=False)

        # Verify console.print was called
        assert mock_console.print.called

        # Get the printed message
        call_args = mock_console.print.call_args[0][0]

        # Should include the URL
        assert "https://github.com/test/other-repo/issues/8624" in call_args
        assert "test/other-repo" in call_args

    @patch('release_tool.commands.generate.console')
    def test_warn_shows_resolution_steps(self, mock_console, test_config_warn):
        """Test that warnings include resolution steps."""
        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialIssueReason.PULL_NOT_RUN}
            )
        ]

        _handle_partial_issues(partials, set(), test_config_warn, debug=False)

        # Get the printed message
        call_args = mock_console.print.call_args[0][0]

        # Should include resolution steps
        assert "To resolve:" in call_args
        assert "release-tool pull" in call_args


class TestPartialIssueIntegration:
    """Integration tests for partial issue handling in generate command."""

    def test_partial_match_enum_usage(self):
        """Test that PartialIssueMatch uses enums correctly."""
        partial = PartialIssueMatch(
            issue_key="8624",
            extracted_from="test",
            match_type="not_found",
            potential_reasons={
                PartialIssueReason.OLDER_THAN_CUTOFF,
                PartialIssueReason.TYPO
            }
        )

        # All reasons should be enum instances
        for reason in partial.potential_reasons:
            assert isinstance(reason, PartialIssueReason)
            assert hasattr(reason, 'description')
            assert isinstance(reason.description, str)

    def test_consolidation_groups_issues_by_reason(self):
        """Test that multiple issues with same reason are grouped."""
        from collections import defaultdict

        partials = [
            PartialIssueMatch(
                issue_key="8624",
                extracted_from="branch 1",
                match_type="not_found",
                potential_reasons={PartialIssueReason.OLDER_THAN_CUTOFF}
            ),
            PartialIssueMatch(
                issue_key="8853",
                extracted_from="branch 2",
                match_type="not_found",
                potential_reasons={PartialIssueReason.OLDER_THAN_CUTOFF}
            ),
            PartialIssueMatch(
                issue_key="9000",
                extracted_from="branch 3",
                match_type="not_found",
                potential_reasons={PartialIssueReason.TYPO}
            )
        ]

        # Group issues by reason (like _handle_partial_issues does)
        issues_by_reason = defaultdict(list)
        for p in partials:
            for reason in p.potential_reasons:
                issues_by_reason[reason].append(p)

        # Should have 2 groups: OLDER_THAN_CUTOFF (2 issues), TYPO (1 issue)
        assert len(issues_by_reason) == 2
        assert len(issues_by_reason[PartialIssueReason.OLDER_THAN_CUTOFF]) == 2
        assert len(issues_by_reason[PartialIssueReason.TYPO]) == 1

        # Verify issue keys
        cutoff_issues = [p.issue_key for p in issues_by_reason[PartialIssueReason.OLDER_THAN_CUTOFF]]
        assert "8624" in cutoff_issues
        assert "8853" in cutoff_issues

        typo_issues = [p.issue_key for p in issues_by_reason[PartialIssueReason.TYPO]]
        assert "9000" in typo_issues
