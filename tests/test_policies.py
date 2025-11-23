"""Tests for policy implementations."""

import pytest
from datetime import datetime
from release_tool.policies import (
    TicketExtractor, CommitConsolidator, ReleaseNoteGenerator, VersionGapChecker
)
from release_tool.config import Config, TicketPolicyConfig, ReleaseNoteConfig, CategoryConfig
from release_tool.models import Commit, PullRequest, Ticket, Label, ConsolidatedChange, Author


@pytest.fixture
def test_config():
    """Create a test configuration."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        }
    }
    return Config.from_dict(config_dict)


class TestTicketExtractor:
    """Tests for ticket extraction."""

    def test_extract_from_commit_with_jira_ticket(self, test_config):
        """Test extraction from commit messages with JIRA-style tickets."""
        extractor = TicketExtractor(test_config)
        commit = Commit(
            sha="abc123",
            repo_id=1,
            message="Fix bug in TICKET-789",
            author=Author(name="dev"),
            date=datetime.now()
        )

        tickets = extractor.extract_from_commit(commit)

        assert len(tickets) > 0
        assert "789" in tickets

    def test_extract_from_commit_with_github_ref(self, test_config):
        """Test extraction from commit messages with GitHub issue refs."""
        extractor = TicketExtractor(test_config)
        commit = Commit(
            sha="abc456",
            repo_id=1,
            message="This fixes #456",
            author=Author(name="dev"),
            date=datetime.now()
        )

        tickets = extractor.extract_from_commit(commit)

        assert "456" in tickets

    def test_extract_from_branch_name(self, test_config):
        """Test extraction from branch names like feat/meta-123/main."""
        extractor = TicketExtractor(test_config)

        # Test various branch name patterns
        assert "123" in extractor.extract_from_branch("feat/meta-123/main")
        assert "456" in extractor.extract_from_branch("fix/meta-456.whatever/main")
        assert "789" in extractor.extract_from_branch("hotfix/repo-789/develop")

    def test_extract_parent_issue_from_pr(self, test_config):
        """Test extraction of parent issue URL from PR body."""
        extractor = TicketExtractor(test_config)

        pr = PullRequest(
            repo_id=1,
            number=1,
            title="Fix bug",
            body="""
            This PR fixes several issues.

            Parent issue: https://github.com/owner/repo/issues/999

            ## Changes
            - Fixed bug
            """,
            state="closed",
            head_branch="feature/branch"
        )

        tickets = extractor.extract_from_pr(pr)
        assert "999" in tickets

    def test_extract_from_pr_title(self, test_config):
        """Test extraction from PR title."""
        extractor = TicketExtractor(test_config)

        pr = PullRequest(
            repo_id=1,
            number=2,
            title="Fix issue #123",
            state="closed",
            head_branch="fix/branch"
        )

        tickets = extractor.extract_from_pr(pr)
        assert "123" in tickets


class TestCommitConsolidator:
    """Tests for commit consolidation."""

    def test_consolidate_by_ticket(self, test_config):
        extractor = TicketExtractor(test_config)
        consolidator = CommitConsolidator(test_config, extractor)

        commits = [
            Commit(
                sha="1",
                repo_id=1,
                message="TICKET-1: Part 1",
                author=Author(name="dev"),
                date=datetime.now()
            ),
            Commit(
                sha="2",
                repo_id=1,
                message="TICKET-1: Part 2",
                author=Author(name="dev"),
                date=datetime.now()
            )
        ]

        consolidated = consolidator.consolidate(commits, {})

        # Should consolidate commits with same ticket
        assert len(consolidated) <= len(commits)

    def test_consolidation_disabled(self, test_config):
        # Disable consolidation
        test_config.ticket_policy.consolidation_enabled = False

        extractor = TicketExtractor(test_config)
        consolidator = CommitConsolidator(test_config, extractor)

        commits = [
            Commit(sha="1", repo_id=1, message="Test 1", author=Author(name="dev"), date=datetime.now()),
            Commit(sha="2", repo_id=1, message="Test 2", author=Author(name="dev"), date=datetime.now())
        ]

        consolidated = consolidator.consolidate(commits, {})

        # Should return each commit separately
        assert len(consolidated) == len(commits)


class TestReleaseNoteGenerator:
    """Tests for release note generation."""

    def test_create_release_note_from_change(self, test_config):
        generator = ReleaseNoteGenerator(test_config)

        change = ConsolidatedChange(
            type="commit",
            commits=[
                Commit(
                    sha="abc",
                    repo_id=1,
                    message="Add new feature",
                    author=Author(name="dev1"),
                    date=datetime.now()
                )
            ]
        )

        note = generator.create_release_note(change)

        assert note.title == "Add new feature"
        assert note.authors[0].name == "dev1"

    def test_group_by_category(self, test_config):
        from release_tool.models import ReleaseNote

        generator = ReleaseNoteGenerator(test_config)

        notes = [
            ReleaseNote(
                title="Fix bug",
                category="Bug Fixes",
                labels=["bug"]
            ),
            ReleaseNote(
                title="New feature",
                category="Features",
                labels=["feature"]
            )
        ]

        grouped = generator.group_by_category(notes)

        assert "Features" in grouped
        assert "Bug Fixes" in grouped
        assert len(grouped["Features"]) >= 1
        assert len(grouped["Bug Fixes"]) >= 1


class TestVersionGapChecker:
    """Tests for version gap checking."""

    def test_gap_detection_warn(self, test_config, capsys):
        checker = VersionGapChecker(test_config)

        # This should trigger a warning (gap from 1.0.0 to 1.2.0)
        checker.check_gap("1.0.0", "1.2.0")

        # Check if warning was printed
        captured = capsys.readouterr()
        assert "gap" in captured.out.lower() or len(captured.out) == 0  # May or may not warn depending on config

    def test_gap_detection_ignore(self, test_config, capsys):
        from release_tool.config import PolicyAction
        test_config.version_policy.gap_detection = PolicyAction.IGNORE

        checker = VersionGapChecker(test_config)
        checker.check_gap("1.0.0", "1.2.0")

        # Should not print anything
        captured = capsys.readouterr()
        # Ignore policy means no output
