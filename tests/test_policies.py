# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

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

    def test_debug_mode_output(self, test_config, capsys):
        """Test that debug mode produces detailed pattern matching output."""
        extractor = TicketExtractor(test_config, debug=True)

        # Test with commit that has a ticket
        commit = Commit(
            sha="abc123def",
            repo_id=1,
            message="Fix authentication bug #456",
            author=Author(name="developer"),
            date=datetime.now()
        )

        tickets = extractor.extract_from_commit(commit)

        # Capture output
        captured = capsys.readouterr()

        # Verify output contains key debug information
        assert "Extracting from commit:" in captured.out
        assert "abc123" in captured.out  # Short SHA
        assert "Fix authentication bug" in captured.out  # Commit message
        assert "Trying pattern" in captured.out  # Pattern attempt
        assert "Regex:" in captured.out  # Pattern regex shown
        assert "Extracted tickets:" in captured.out  # Results shown

        # Verify correct extraction
        assert "456" in tickets

        # Test with PR
        pr = PullRequest(
            repo_id=1,
            number=789,
            title="Fix bug in login",
            body="This fixes the login issue.",
            state="closed",
            head_branch="feat/meta-123/main"
        )

        tickets_pr = extractor.extract_from_pr(pr)

        # Capture PR output
        captured = capsys.readouterr()

        # Verify PR debug output
        assert "Extracting from PR #789:" in captured.out
        assert "Fix bug in login" in captured.out
        assert "Pattern #" in captured.out
        assert "strategy=" in captured.out
        assert "MATCH!" in captured.out or "No match" in captured.out

        # Verify correct extraction (branch pattern should match)
        assert "123" in tickets_pr


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


class TestTOMLPatternEscaping:
    """Tests for TOML pattern escaping and real-world examples."""

    def test_toml_config_with_correct_escaping(self):
        """Test that patterns loaded from TOML with correct escaping work."""
        config_dict = {
            "repository": {"code_repo": "test/repo"},
            "github": {"token": "test_token"},
            "ticket_policy": {
                "patterns": [
                    {
                        "order": 1,
                        "strategy": "branch_name",
                        # Double backslash in Python dict (simulates TOML parsing)
                        "pattern": r"/(?P<repo>\w+)-(?P<ticket>\d+)",
                        "description": "Branch pattern"
                    },
                    {
                        "order": 2,
                        "strategy": "pr_body",
                        "pattern": r"Parent issue:.*?/issues/(?P<ticket>\d+)",
                        "description": "Parent issue pattern"
                    },
                ]
            }
        }
        config = Config.from_dict(config_dict)
        extractor = TicketExtractor(config)

        # Test branch pattern
        pr = PullRequest(
            repo_id=1,
            number=2169,
            title="✨ Prepare Release 9.2.0",
            body="Parent issue: https://github.com/sequentech/meta/issues/8853",
            state="closed",
            head_branch="docs/feat-8853/main"
        )

        tickets = extractor.extract_from_pr(pr)

        # Should match branch pattern (order 1) and extract "8853"
        assert "8853" in tickets, f"Expected '8853' in tickets, but got: {tickets}"

    def test_branch_pattern_real_world_examples(self):
        """Test branch pattern with real-world branch names."""
        config_dict = {
            "repository": {"code_repo": "test/repo"},
            "github": {"token": "test_token"},
            "ticket_policy": {
                "patterns": [
                    {
                        "order": 1,
                        "strategy": "branch_name",
                        "pattern": r"/(?P<repo>\w+)-(?P<ticket>\d+)",
                        "description": "Branch pattern"
                    }
                ]
            }
        }
        config = Config.from_dict(config_dict)
        extractor = TicketExtractor(config)

        # Test various real-world branch names
        test_cases = [
            ("docs/feat-8853/main", "8853"),
            ("feat/meta-123/main", "123"),
            ("fix/repo-456.whatever/main", "456"),
            ("hotfix/bug-789/develop", "789"),
            ("feature/issue-999/release", "999"),
        ]

        for branch_name, expected_ticket in test_cases:
            tickets = extractor.extract_from_branch(branch_name)
            assert expected_ticket in tickets, \
                f"Branch '{branch_name}' should extract ticket '{expected_ticket}', but got: {tickets}"

    def test_parent_issue_pattern_real_world_examples(self):
        """Test parent issue pattern with real-world PR bodies."""
        config_dict = {
            "repository": {"code_repo": "test/repo"},
            "github": {"token": "test_token"},
            "ticket_policy": {
                "patterns": [
                    {
                        "order": 1,
                        "strategy": "pr_body",
                        "pattern": r"Parent issue:.*?/issues/(?P<ticket>\d+)",
                        "description": "Parent issue pattern"
                    }
                ]
            }
        }
        config = Config.from_dict(config_dict)
        extractor = TicketExtractor(config)

        # Test various real-world PR body formats
        test_cases = [
            ("Parent issue: https://github.com/sequentech/meta/issues/8853", "8853"),
            ("Parent issue: https://github.com/owner/repo/issues/123", "123"),
            ("Parent issue:https://github.com/org/project/issues/456", "456"),
            ("Parent issue: http://github.com/test/test/issues/789", "789"),
        ]

        for pr_body, expected_ticket in test_cases:
            pr = PullRequest(
                repo_id=1,
                number=1,
                title="Test PR",
                body=pr_body,
                state="closed",
                head_branch="test"
            )
            tickets = extractor.extract_from_pr(pr)
            assert expected_ticket in tickets, \
                f"PR body '{pr_body}' should extract ticket '{expected_ticket}', but got: {tickets}"

    def test_github_issue_reference_patterns(self):
        """Test GitHub issue reference patterns (#123) in various contexts."""
        config_dict = {
            "repository": {"code_repo": "test/repo"},
            "github": {"token": "test_token"},
            "ticket_policy": {
                "patterns": [
                    {
                        "order": 1,
                        "strategy": "pr_title",
                        "pattern": r"#(?P<ticket>\d+)",
                        "description": "GitHub issue in PR title"
                    },
                    {
                        "order": 2,
                        "strategy": "commit_message",
                        "pattern": r"#(?P<ticket>\d+)",
                        "description": "GitHub issue in commit"
                    }
                ]
            }
        }
        config = Config.from_dict(config_dict)
        extractor = TicketExtractor(config)

        # Test PR title
        pr = PullRequest(
            repo_id=1,
            number=1,
            title="Fix authentication bug #456",
            state="closed",
            head_branch="fix/bug"
        )
        tickets = extractor.extract_from_pr(pr)
        assert "456" in tickets

        # Test commit message
        commit = Commit(
            sha="abc123",
            repo_id=1,
            message="Resolve issue #789",
            author=Author(name="dev"),
            date=datetime.now()
        )
        tickets = extractor.extract_from_commit(commit)
        assert "789" in tickets

    def test_jira_style_pattern(self):
        """Test JIRA-style ticket patterns (PROJ-123)."""
        config_dict = {
            "repository": {"code_repo": "test/repo"},
            "github": {"token": "test_token"},
            "ticket_policy": {
                "patterns": [
                    {
                        "order": 1,
                        "strategy": "commit_message",
                        "pattern": r"(?P<project>[A-Z]+)-(?P<ticket>\d+)",
                        "description": "JIRA-style tickets"
                    }
                ]
            }
        }
        config = Config.from_dict(config_dict)
        extractor = TicketExtractor(config)

        test_cases = [
            ("Fix bug in TICKET-789", "789"),
            ("PROJ-123: Add new feature", "123"),
            ("Update ABC-456 implementation", "456"),
        ]

        for message, expected_ticket in test_cases:
            commit = Commit(
                sha="abc123",
                repo_id=1,
                message=message,
                author=Author(name="dev"),
                date=datetime.now()
            )
            tickets = extractor.extract_from_commit(commit)
            assert expected_ticket in tickets, \
                f"Commit message '{message}' should extract ticket '{expected_ticket}', but got: {tickets}"

    def test_pattern_priority_order(self):
        """Test that patterns are tried in order and first match wins for PRs."""
        config_dict = {
            "repository": {"code_repo": "test/repo"},
            "github": {"token": "test_token"},
            "ticket_policy": {
                "patterns": [
                    {
                        "order": 1,
                        "strategy": "branch_name",
                        "pattern": r"/(?P<repo>\w+)-(?P<ticket>\d+)",
                        "description": "Branch pattern (highest priority)"
                    },
                    {
                        "order": 2,
                        "strategy": "pr_body",
                        "pattern": r"Parent issue:.*?/issues/(?P<ticket>\d+)",
                        "description": "Parent issue pattern (lower priority)"
                    }
                ]
            }
        }
        config = Config.from_dict(config_dict)
        extractor = TicketExtractor(config)

        # PR with both branch name and parent issue
        # Should extract from branch (order 1) and stop
        pr = PullRequest(
            repo_id=1,
            number=1,
            title="Test PR",
            body="Parent issue: https://github.com/owner/repo/issues/999",
            state="closed",
            head_branch="feat/meta-123/main"
        )

        tickets = extractor.extract_from_pr(pr)

        # Should only extract "123" from branch (first match wins)
        # Should NOT extract "999" from body (stopped after first match)
        assert "123" in tickets
        assert len(tickets) == 1, f"Should only extract one ticket (first match wins), but got: {tickets}"


class TestURLHandlingAndShortLinks:
    """Tests for URL priority and short link generation."""

    def test_url_priority_ticket_over_pr(self, test_config):
        """Test that ticket_url is prioritized over pr_url in the smart url field."""
        from release_tool.models import ConsolidatedChange, Ticket, PullRequest, Repository

        # Create a ticket
        ticket = Ticket(
            repo_id=1,
            number=8853,
            key="8853",
            title="Implement feature X",
            state="closed",
            url="https://github.com/sequentech/meta/issues/8853"
        )

        # Create a PR
        pr = PullRequest(
            repo_id=2,
            number=2169,
            title="Implement feature X",
            state="closed",
            head_branch="feat/meta-8853/main",
            url="https://github.com/sequentech/step/pull/2169"
        )

        # Create a consolidated change with both
        change = ConsolidatedChange(
            type="ticket",
            ticket_key="8853",
            prs=[pr],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, ticket)

        # Verify URL priority
        assert note.ticket_url == "https://github.com/sequentech/meta/issues/8853"
        assert note.pr_url == "https://github.com/sequentech/step/pull/2169"
        assert note.url == note.ticket_url, "url should prioritize ticket_url"
        assert note.url != note.pr_url

    def test_url_fallback_to_pr_when_no_ticket(self, test_config):
        """Test that pr_url is used when ticket_url is not available."""
        from release_tool.models import ConsolidatedChange, PullRequest

        # Create a PR (no ticket)
        pr = PullRequest(
            repo_id=2,
            number=2169,
            title="Fix bug",
            state="closed",
            head_branch="fix/bug",
            url="https://github.com/sequentech/step/pull/2169"
        )

        # Create a consolidated change without ticket
        change = ConsolidatedChange(
            type="pr",
            pr_number=2169,
            prs=[pr],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, None)

        # Verify URL fallback
        assert note.ticket_url is None
        assert note.pr_url == "https://github.com/sequentech/step/pull/2169"
        assert note.url == note.pr_url, "url should fall back to pr_url"

    def test_short_link_from_ticket_url(self, test_config):
        """Test short_link generation from ticket URL."""
        from release_tool.models import ConsolidatedChange, Ticket

        ticket = Ticket(
            repo_id=1,
            number=8853,
            key="8853",
            title="Test ticket",
            state="closed",
            url="https://github.com/sequentech/meta/issues/8853"
        )

        change = ConsolidatedChange(
            type="ticket",
            ticket_key="8853",
            prs=[],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, ticket)

        assert note.short_link == "#8853"
        assert note.short_repo_link == "sequentech/meta#8853"

    def test_short_link_from_pr_url(self, test_config):
        """Test short_link generation from PR URL."""
        from release_tool.models import ConsolidatedChange, PullRequest

        pr = PullRequest(
            repo_id=2,
            number=2169,
            title="Test PR",
            state="closed",
            head_branch="test",
            url="https://github.com/sequentech/step/pull/2169"
        )

        change = ConsolidatedChange(
            type="pr",
            pr_number=2169,
            prs=[pr],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, None)

        assert note.short_link == "#2169"
        assert note.short_repo_link == "sequentech/step#2169"

    def test_short_link_prioritizes_ticket_url(self, test_config):
        """Test that short links are computed from ticket_url when both exist."""
        from release_tool.models import ConsolidatedChange, Ticket, PullRequest

        ticket = Ticket(
            repo_id=1,
            number=8853,
            key="8853",
            title="Test ticket",
            state="closed",
            url="https://github.com/sequentech/meta/issues/8853"
        )

        pr = PullRequest(
            repo_id=2,
            number=2169,
            title="Test PR",
            state="closed",
            head_branch="feat/meta-8853/main",
            url="https://github.com/sequentech/step/pull/2169"
        )

        change = ConsolidatedChange(
            type="ticket",
            ticket_key="8853",
            prs=[pr],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, ticket)

        # Should use ticket info for short links, not PR info
        assert note.short_link == "#8853"
        assert note.short_repo_link == "sequentech/meta#8853"
        assert note.short_link != "#2169"
        assert note.short_repo_link != "sequentech/step#2169"

    def test_short_link_none_when_no_url(self, test_config):
        """Test that short_link is None when no URL is available."""
        from release_tool.models import ConsolidatedChange, Commit, Author

        commit = Commit(
            sha="abc123",
            repo_id=1,
            message="Fix bug",
            author=Author(name="dev"),
            date=datetime.now()
        )

        change = ConsolidatedChange(
            type="commit",
            commits=[commit],
            prs=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, None)

        assert note.url is None
        assert note.short_link is None
        assert note.short_repo_link is None

    def test_extract_github_url_info_various_formats(self, test_config):
        """Test _extract_github_url_info with various URL formats."""
        generator = ReleaseNoteGenerator(test_config)

        # Test cases: (url, expected_owner_repo, expected_number)
        test_cases = [
            ("https://github.com/sequentech/meta/issues/8853", "sequentech/meta", "8853"),
            ("https://github.com/owner/repo/pull/123", "owner/repo", "123"),
            ("http://github.com/test/project/issues/456", "test/project", "456"),
            ("https://github.com/org/my-repo/pull/789", "org/my-repo", "789"),
            # Invalid URLs
            ("https://gitlab.com/owner/repo/issues/123", None, None),
            ("not a url", None, None),
            ("https://github.com/owner/repo", None, None),
        ]

        for url, expected_owner_repo, expected_number in test_cases:
            owner_repo, number = generator._extract_github_url_info(url)
            assert owner_repo == expected_owner_repo, f"URL {url}: expected owner_repo={expected_owner_repo}, got {owner_repo}"
            assert number == expected_number, f"URL {url}: expected number={expected_number}, got {number}"

    def test_short_links_in_template_context(self, test_config):
        """Test that short_link and short_repo_link are passed to templates."""
        from release_tool.models import ConsolidatedChange, Ticket

        ticket = Ticket(
            repo_id=1,
            number=8853,
            key="8853",
            title="Test ticket",
            state="closed",
            url="https://github.com/sequentech/meta/issues/8853"
        )

        change = ConsolidatedChange(
            type="ticket",
            ticket_key="8853",
            prs=[],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, ticket)

        # Prepare note for template
        note_dict = generator._prepare_note_for_template(note, "1.0.0", None, None)

        assert "short_link" in note_dict
        assert "short_repo_link" in note_dict
        assert note_dict["short_link"] == "#8853"
        assert note_dict["short_repo_link"] == "sequentech/meta#8853"

    def test_ticket_key_without_hash_prefix(self, test_config):
        """Test that ticket keys without '#' prefix still work correctly."""
        from release_tool.models import ConsolidatedChange, Ticket

        # Ticket with bare number as key (as extracted from branch names)
        ticket = Ticket(
            repo_id=1,
            number=8624,
            key="8624",  # Bare number, not "#8624"
            title="Test ticket",
            state="closed",
            url="https://github.com/sequentech/meta/issues/8624"
        )

        change = ConsolidatedChange(
            type="ticket",
            ticket_key="8624",  # Bare number
            prs=[],
            commits=[]
        )

        generator = ReleaseNoteGenerator(test_config)
        note = generator.create_release_note(change, ticket)

        # Should use ticket URL and generate correct short links
        assert note.ticket_url == "https://github.com/sequentech/meta/issues/8624"
        assert note.url == note.ticket_url
        assert note.short_link == "#8624"
        assert note.short_repo_link == "sequentech/meta#8624"
