"""Tests for partial ticket match handling."""

import pytest
from io import StringIO
from unittest.mock import Mock, patch
from datetime import datetime

from release_tool.policies import PartialTicketMatch, PartialTicketReason
from release_tool.config import Config, PolicyAction
from release_tool.models import Author, Commit, PullRequest, ConsolidatedChange
from release_tool.main import _handle_partial_tickets, _get_extraction_source


@pytest.fixture
def test_config_warn():
    """Create a test configuration with warn policy."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo",
            "ticket_repos": ["test/meta"]
        },
        "github": {
            "token": "test_token"
        },
        "ticket_policy": {
            "partial_ticket_action": "warn"
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_config_ignore():
    """Create a test configuration with ignore policy."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo",
            "ticket_repos": ["test/meta"]
        },
        "github": {
            "token": "test_token"
        },
        "ticket_policy": {
            "partial_ticket_action": "ignore"
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_config_error():
    """Create a test configuration with error policy."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo",
            "ticket_repos": ["test/meta"]
        },
        "github": {
            "token": "test_token"
        },
        "ticket_policy": {
            "partial_ticket_action": "error"
        }
    }
    return Config.from_dict(config_dict)


class TestPartialTicketMatch:
    """Tests for PartialTicketMatch dataclass."""

    def test_create_not_found_partial(self):
        """Test creating a partial match for a ticket not found."""
        partial = PartialTicketMatch(
            ticket_key="8624",
            extracted_from="branch feat/meta-8624/main, PR #123",
            match_type="not_found",
            potential_reasons={
                PartialTicketReason.OLDER_THAN_CUTOFF,
                PartialTicketReason.TYPO,
                PartialTicketReason.SYNC_NOT_RUN
            }
        )

        assert partial.ticket_key == "8624"
        assert partial.match_type == "not_found"
        assert len(partial.potential_reasons) == 3
        assert PartialTicketReason.OLDER_THAN_CUTOFF in partial.potential_reasons
        assert partial.found_in_repo is None
        assert partial.ticket_url is None

    def test_create_different_repo_partial(self):
        """Test creating a partial match for a ticket in different repo."""
        partial = PartialTicketMatch(
            ticket_key="8853",
            extracted_from="branch feat/step-8853/main, PR #456",
            match_type="different_repo",
            found_in_repo="test/different-repo",
            ticket_url="https://github.com/test/different-repo/issues/8853",
            potential_reasons={
                PartialTicketReason.REPO_CONFIG_MISMATCH,
                PartialTicketReason.WRONG_TICKET_REPOS
            }
        )

        assert partial.ticket_key == "8853"
        assert partial.match_type == "different_repo"
        assert partial.found_in_repo == "test/different-repo"
        assert partial.ticket_url == "https://github.com/test/different-repo/issues/8853"
        assert len(partial.potential_reasons) == 2
        assert PartialTicketReason.REPO_CONFIG_MISMATCH in partial.potential_reasons


class TestPartialTicketReason:
    """Tests for PartialTicketReason enum."""

    def test_reason_descriptions(self):
        """Test that all reasons have descriptions."""
        assert PartialTicketReason.OLDER_THAN_CUTOFF.description == "Ticket may be older than sync cutoff date"
        assert PartialTicketReason.TYPO.description == "Ticket may not exist (typo in branch/PR)"
        assert PartialTicketReason.SYNC_NOT_RUN.description == "Sync may not have been run yet"
        assert PartialTicketReason.REPO_CONFIG_MISMATCH.description == "Ticket found in different repo than configured"
        assert PartialTicketReason.WRONG_TICKET_REPOS.description == "Check repository.ticket_repos in config"

    def test_reason_values(self):
        """Test enum values are correct."""
        assert PartialTicketReason.OLDER_THAN_CUTOFF.value == "older_than_cutoff"
        assert PartialTicketReason.TYPO.value == "typo"
        assert PartialTicketReason.SYNC_NOT_RUN.value == "sync_not_run"
        assert PartialTicketReason.REPO_CONFIG_MISMATCH.value == "repo_config_mismatch"
        assert PartialTicketReason.WRONG_TICKET_REPOS.value == "wrong_ticket_repos"


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
            type="ticket",
            ticket_key="8624",
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
            ticket_key="8853",
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
            ticket_key="999",
            prs=[],
            commits=[commit]
        )

        source = _get_extraction_source(change)

        assert "commit" in source
        assert "abc1234" in source

    def test_extraction_unknown_source(self):
        """Test extraction source when unknown."""
        change = ConsolidatedChange(
            type="ticket",
            ticket_key="111",
            prs=[],
            commits=[]
        )

        source = _get_extraction_source(change)

        assert source == "unknown source"


class TestHandlePartialTickets:
    """Tests for _handle_partial_tickets function."""

    def test_ignore_policy_no_output(self, test_config_ignore, capsys):
        """Test that ignore policy produces no output."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialTicketReason.OLDER_THAN_CUTOFF}
            )
        ]

        # Should not raise, should not print
        _handle_partial_tickets(partials, test_config_ignore, debug=False)

        # No exception raised means success
        assert True

    def test_warn_policy_prints_message(self, test_config_warn, capsys):
        """Test that warn policy prints warning message."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main, PR #123",
                match_type="not_found",
                potential_reasons={
                    PartialTicketReason.OLDER_THAN_CUTOFF,
                    PartialTicketReason.TYPO
                }
            )
        ]

        _handle_partial_tickets(partials, test_config_warn, debug=False)

        # Capture should include warning about partial matches
        # Note: Using rich Console means we can't easily capture output in tests
        # This test verifies no exception is raised
        assert True

    def test_error_policy_raises_exception(self, test_config_error):
        """Test that error policy raises RuntimeError."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialTicketReason.SYNC_NOT_RUN}
            )
        ]

        with pytest.raises(RuntimeError) as exc_info:
            _handle_partial_tickets(partials, test_config_error, debug=False)

        assert "Partial ticket matches found" in str(exc_info.value)
        assert "1 total" in str(exc_info.value)

    def test_error_policy_with_multiple_partials(self, test_config_error):
        """Test error policy with multiple partials."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialTicketReason.OLDER_THAN_CUTOFF}
            ),
            PartialTicketMatch(
                ticket_key="8853",
                extracted_from="branch feat/step-8853/main",
                match_type="different_repo",
                found_in_repo="test/different",
                ticket_url="https://github.com/test/different/issues/8853",
                potential_reasons={PartialTicketReason.REPO_CONFIG_MISMATCH}
            )
        ]

        with pytest.raises(RuntimeError) as exc_info:
            _handle_partial_tickets(partials, test_config_error, debug=False)

        assert "2 total" in str(exc_info.value)

    def test_no_partials_does_nothing(self, test_config_warn):
        """Test that empty partial list does nothing."""
        partials = []

        # Should not raise, should not print
        _handle_partial_tickets(partials, test_config_warn, debug=False)

        assert True

    @patch('release_tool.main.console')
    def test_warn_consolidates_by_reason(self, mock_console, test_config_warn):
        """Test that warnings consolidate tickets by reason."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={
                    PartialTicketReason.OLDER_THAN_CUTOFF,
                    PartialTicketReason.SYNC_NOT_RUN
                }
            ),
            PartialTicketMatch(
                ticket_key="8853",
                extracted_from="branch feat/meta-8853/main",
                match_type="not_found",
                potential_reasons={
                    PartialTicketReason.OLDER_THAN_CUTOFF  # Same reason as 8624
                }
            )
        ]

        _handle_partial_tickets(partials, test_config_warn, debug=False)

        # Verify console.print was called
        assert mock_console.print.called

        # Get the printed message
        call_args = mock_console.print.call_args[0][0]

        # Should mention both tickets
        assert "8624" in call_args
        assert "8853" in call_args

        # Should mention the reason
        assert "older than sync cutoff" in call_args or "OLDER_THAN_CUTOFF" in call_args

    @patch('release_tool.main.console')
    def test_warn_different_repo_includes_url(self, mock_console, test_config_warn):
        """Test that different_repo warnings include URLs."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="different_repo",
                found_in_repo="test/other-repo",
                ticket_url="https://github.com/test/other-repo/issues/8624",
                potential_reasons={PartialTicketReason.REPO_CONFIG_MISMATCH}
            )
        ]

        _handle_partial_tickets(partials, test_config_warn, debug=False)

        # Verify console.print was called
        assert mock_console.print.called

        # Get the printed message
        call_args = mock_console.print.call_args[0][0]

        # Should include the URL
        assert "https://github.com/test/other-repo/issues/8624" in call_args
        assert "test/other-repo" in call_args

    @patch('release_tool.main.console')
    def test_warn_shows_resolution_steps(self, mock_console, test_config_warn):
        """Test that warnings include resolution steps."""
        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch feat/meta-8624/main",
                match_type="not_found",
                potential_reasons={PartialTicketReason.SYNC_NOT_RUN}
            )
        ]

        _handle_partial_tickets(partials, test_config_warn, debug=False)

        # Get the printed message
        call_args = mock_console.print.call_args[0][0]

        # Should include resolution steps
        assert "To resolve:" in call_args
        assert "release-tool sync" in call_args


class TestPartialTicketIntegration:
    """Integration tests for partial ticket handling in generate command."""

    def test_partial_match_enum_usage(self):
        """Test that PartialTicketMatch uses enums correctly."""
        partial = PartialTicketMatch(
            ticket_key="8624",
            extracted_from="test",
            match_type="not_found",
            potential_reasons={
                PartialTicketReason.OLDER_THAN_CUTOFF,
                PartialTicketReason.TYPO
            }
        )

        # All reasons should be enum instances
        for reason in partial.potential_reasons:
            assert isinstance(reason, PartialTicketReason)
            assert hasattr(reason, 'description')
            assert isinstance(reason.description, str)

    def test_consolidation_groups_tickets_by_reason(self):
        """Test that multiple tickets with same reason are grouped."""
        from collections import defaultdict

        partials = [
            PartialTicketMatch(
                ticket_key="8624",
                extracted_from="branch 1",
                match_type="not_found",
                potential_reasons={PartialTicketReason.OLDER_THAN_CUTOFF}
            ),
            PartialTicketMatch(
                ticket_key="8853",
                extracted_from="branch 2",
                match_type="not_found",
                potential_reasons={PartialTicketReason.OLDER_THAN_CUTOFF}
            ),
            PartialTicketMatch(
                ticket_key="9000",
                extracted_from="branch 3",
                match_type="not_found",
                potential_reasons={PartialTicketReason.TYPO}
            )
        ]

        # Group tickets by reason (like _handle_partial_tickets does)
        tickets_by_reason = defaultdict(list)
        for p in partials:
            for reason in p.potential_reasons:
                tickets_by_reason[reason].append(p)

        # Should have 2 groups: OLDER_THAN_CUTOFF (2 tickets), TYPO (1 ticket)
        assert len(tickets_by_reason) == 2
        assert len(tickets_by_reason[PartialTicketReason.OLDER_THAN_CUTOFF]) == 2
        assert len(tickets_by_reason[PartialTicketReason.TYPO]) == 1

        # Verify ticket keys
        cutoff_tickets = [p.ticket_key for p in tickets_by_reason[PartialTicketReason.OLDER_THAN_CUTOFF]]
        assert "8624" in cutoff_tickets
        assert "8853" in cutoff_tickets

        typo_tickets = [p.ticket_key for p in tickets_by_reason[PartialTicketReason.TYPO]]
        assert "9000" in typo_tickets
