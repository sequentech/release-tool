# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for release_notes_inclusion_policy filtering."""

import pytest
from release_tool.commands.generate import _filter_by_inclusion_policy
from release_tool.config import Config
from release_tool.models import ConsolidatedChange, Author


@pytest.fixture
def config_default_policy():
    """Config with default inclusion policy ["tickets", "pull-requests"]."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "ticket_policy": {
            "release_notes_inclusion_policy": ["tickets", "pull-requests"]
        }
    })


@pytest.fixture
def config_tickets_only():
    """Config with tickets-only policy."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "ticket_policy": {
            "release_notes_inclusion_policy": ["tickets"]
        }
    })


@pytest.fixture
def config_commits_only():
    """Config with commits-only policy."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "ticket_policy": {
            "release_notes_inclusion_policy": ["commits"]
        }
    })


@pytest.fixture
def config_all_types():
    """Config including all types."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "ticket_policy": {
            "release_notes_inclusion_policy": ["tickets", "pull-requests", "commits"]
        }
    })


@pytest.fixture
def config_prs_only():
    """Config with PRs-only policy."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "ticket_policy": {
            "release_notes_inclusion_policy": ["pull-requests"]
        }
    })


@pytest.fixture
def config_empty_policy():
    """Config with empty inclusion policy."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "ticket_policy": {
            "release_notes_inclusion_policy": []
        }
    })


@pytest.fixture
def sample_changes():
    """Sample consolidated changes covering all types."""
    from release_tool.models import Commit, PullRequest, Ticket, Label
    from datetime import datetime

    author = Author(name="Test User", username="testuser", email="test@example.com")

    return [
        # Type: ticket (PR with ticket)
        ConsolidatedChange(
            type="ticket",
            ticket_key="#123",
            ticket=Ticket(
                repo_id=1,
                number=123,
                key="123",
                title="Fix authentication bug",
                state="closed",
                labels=[Label(name="bug")]
            ),
            prs=[
                PullRequest(
                    repo_id=1,
                    number=100,
                    title="Fix authentication bug",
                    state="merged",
                    author=author,
                    labels=[Label(name="bug")]
                )
            ],
            commits=[]
        ),
        # Type: pr (PR without ticket)
        ConsolidatedChange(
            type="pr",
            prs=[
                PullRequest(
                    repo_id=1,
                    number=101,
                    title="Improve performance",
                    state="merged",
                    author=author,
                    labels=[Label(name="enhancement")]
                )
            ],
            commits=[]
        ),
        # Type: commit (standalone commit)
        ConsolidatedChange(
            type="commit",
            commits=[
                Commit(
                    sha="ghi789",
                    repo_id=1,
                    message="Update README",
                    author=author,
                    date=datetime.now()
                )
            ],
            prs=[]
        ),
        # Type: ticket (another ticketed change)
        ConsolidatedChange(
            type="ticket",
            ticket_key="#124",
            ticket=Ticket(
                repo_id=1,
                number=124,
                key="124",
                title="Add new feature",
                state="closed",
                labels=[Label(name="feature")]
            ),
            prs=[
                PullRequest(
                    repo_id=1,
                    number=102,
                    title="Add new feature",
                    state="merged",
                    author=author,
                    labels=[Label(name="feature")]
                )
            ],
            commits=[]
        ),
    ]


def test_default_policy_excludes_standalone_commits(config_default_policy, sample_changes):
    """Test that default policy ["tickets", "pull-requests"] excludes standalone commits."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_default_policy, debug=False)

    # Should include 3 changes: 2 tickets + 1 PR
    assert len(filtered) == 3

    # Should include ticketed changes
    assert any(c.ticket_key == "#123" for c in filtered)
    assert any(c.ticket_key == "#124" for c in filtered)

    # Should include PR without ticket
    assert any(c.type == "pr" and len(c.prs) > 0 and c.prs[0].number == 101 for c in filtered)

    # Should NOT include standalone commit
    assert not any(c.type == "commit" for c in filtered)


def test_tickets_only_policy(config_tickets_only, sample_changes):
    """Test that tickets-only policy excludes PRs without tickets and commits."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_tickets_only, debug=False)

    # Should include only 2 ticketed changes
    assert len(filtered) == 2

    # Should include ticketed changes
    assert any(c.ticket_key == "#123" for c in filtered)
    assert any(c.ticket_key == "#124" for c in filtered)

    # Should NOT include PR without ticket (type should not be "pr")
    assert not any(c.type == "pr" for c in filtered)

    # Should NOT include standalone commit
    assert not any(c.type == "commit" for c in filtered)


def test_commits_only_policy(config_commits_only, sample_changes):
    """Test that commits-only policy includes only standalone commits."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_commits_only, debug=False)

    # Should include only 1 standalone commit
    assert len(filtered) == 1
    assert filtered[0].type == "commit"
    assert len(filtered[0].commits) == 1
    assert filtered[0].commits[0].message == "Update README"


def test_all_types_policy(config_all_types, sample_changes):
    """Test that all-types policy includes everything."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_all_types, debug=False)

    # Should include all 4 changes
    assert len(filtered) == 4

    # Verify all types are present
    types = {c.type for c in filtered}
    assert types == {"ticket", "pr", "commit"}


def test_prs_only_policy(config_prs_only, sample_changes):
    """Test that PRs-only policy includes only PRs without tickets."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_prs_only, debug=False)

    # Should include only 1 PR without ticket
    assert len(filtered) == 1
    assert filtered[0].type == "pr"
    assert len(filtered[0].prs) == 1
    assert filtered[0].prs[0].number == 101


def test_empty_policy_excludes_everything(config_empty_policy, sample_changes):
    """Test that empty policy excludes all changes."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_empty_policy, debug=False)

    # Should exclude everything
    assert len(filtered) == 0


def test_filtered_commits_not_in_counts(config_default_policy):
    """Test that excluded changes don't affect counts."""
    from release_tool.models import Commit, PullRequest, Ticket
    from datetime import datetime

    author = Author(name="Test", username="test", email="test@example.com")

    changes = [
        ConsolidatedChange(
            type="ticket",
            ticket_key="#1",
            ticket=Ticket(repo_id=1, number=1, key="1", title="Ticket 1", state="closed"),
            prs=[],
            commits=[]
        ),
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="abc", repo_id=1, message="Commit 1", author=author, date=datetime.now())],
            prs=[]
        ),
        ConsolidatedChange(
            type="pr",
            prs=[PullRequest(repo_id=1, number=1, title="PR 1", state="merged", author=author)],
            commits=[]
        ),
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="def", repo_id=1, message="Commit 2", author=author, date=datetime.now())],
            prs=[]
        ),
    ]

    filtered = _filter_by_inclusion_policy(changes, config_default_policy, debug=False)

    # Only 2 should remain (1 ticket + 1 PR)
    # Standalone commits should be excluded
    assert len(filtered) == 2

    # Count should reflect only included changes
    ticket_count = sum(1 for c in filtered if c.type == "ticket")
    pr_count = sum(1 for c in filtered if c.type == "pr")
    commit_count = sum(1 for c in filtered if c.type == "commit")

    assert ticket_count == 1
    assert pr_count == 1
    assert commit_count == 0  # No standalone commits


def test_excluded_commits_not_in_other_category(config_default_policy):
    """Test that excluded commits don't appear in 'Other' category."""
    from release_tool.models import Commit, PullRequest
    from datetime import datetime

    author = Author(name="Test", username="test", email="test@example.com")

    # Create changes that would go to "Other" category
    changes = [
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="abc", repo_id=1, message="Standalone commit", author=author, date=datetime.now())],
            prs=[]
        ),
        ConsolidatedChange(
            type="pr",
            prs=[PullRequest(repo_id=1, number=1, title="Untagged PR", state="merged", author=author, labels=[])],
            commits=[]
        ),
    ]

    filtered = _filter_by_inclusion_policy(changes, config_default_policy, debug=False)

    # Should only include the PR, not the commit
    assert len(filtered) == 1
    assert filtered[0].type == "pr"


def test_excluded_commits_not_rendered(config_default_policy):
    """Test that excluded commits don't appear in final output."""
    from release_tool.policies import ReleaseNoteGenerator
    from release_tool.models import Commit, Ticket, Label
    from datetime import datetime

    author = Author(name="Test", username="test", email="test@example.com")

    changes = [
        ConsolidatedChange(
            type="ticket",
            ticket_key="#123",
            ticket=Ticket(
                repo_id=1,
                number=123,
                key="123",
                title="Feature with ticket",
                state="closed",
                labels=[Label(name="feature")]
            ),
            prs=[],
            commits=[]
        ),
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="abc", repo_id=1, message="Standalone commit", author=author, date=datetime.now())],
            prs=[]
        ),
    ]

    # Filter first
    filtered = _filter_by_inclusion_policy(changes, config_default_policy, debug=False)

    # Convert to ReleaseNotes and render
    generator = ReleaseNoteGenerator(config_default_policy)
    release_notes = [generator.create_release_note(c, c.ticket) for c in filtered]
    grouped = generator.group_by_category(release_notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Should include the ticket
    assert "Feature with ticket" in output

    # Should NOT include the standalone commit
    assert "Standalone commit" not in output


def test_debug_mode_shows_exclusion_info(config_default_policy, sample_changes, capsys):
    """Test that debug mode displays exclusion information."""
    _filter_by_inclusion_policy(sample_changes, config_default_policy, debug=True)

    captured = capsys.readouterr()

    # Should show filtering information
    assert "Filtered by release_notes_inclusion_policy" in captured.out or "release_notes_inclusion_policy" in captured.out

    # Should show that 1 commit was excluded
    assert "1" in captured.out and "commit" in captured.out.lower()


def test_ticketed_pr_included_with_tickets_policy(config_tickets_only):
    """Test that PRs with tickets are included when policy is 'tickets'."""
    author = Author(name="Test", username="test")

    changes = [
        # This is a PR with a ticket, so type="ticket"
        ConsolidatedChange(
            type="ticket",
            title="PR with ticket",
            ticket_key="#123",
            pr_numbers=[100],
            authors=[author]
        ),
    ]

    filtered = _filter_by_inclusion_policy(changes, config_tickets_only, debug=False)

    # Should be included because type="ticket"
    assert len(filtered) == 1
    assert filtered[0].ticket_key == "#123"


def test_no_debug_output_when_nothing_filtered(config_all_types, sample_changes, capsys):
    """Test that debug mode doesn't show messages when nothing is filtered."""
    _filter_by_inclusion_policy(sample_changes, config_all_types, debug=True)

    captured = capsys.readouterr()

    # Should NOT show filtering messages when everything is included
    assert "Filtered by" not in captured.out or "0" in captured.out


def test_preserves_order(config_default_policy, sample_changes):
    """Test that filtering preserves the original order of changes."""
    filtered = _filter_by_inclusion_policy(sample_changes, config_default_policy, debug=False)

    # Extract types in order
    types = [c.type for c in filtered]

    # Should preserve order: ticket, pr, ticket (commit was removed)
    assert types == ["ticket", "pr", "ticket"]

    # Verify specific changes by ticket_key and PR number
    assert filtered[0].ticket_key == "#123"  # First ticket
    assert filtered[1].prs[0].number == 101  # PR without ticket
    assert filtered[2].ticket_key == "#124"  # Second ticket


def test_empty_input(config_default_policy):
    """Test filtering with empty input list."""
    filtered = _filter_by_inclusion_policy([], config_default_policy, debug=False)
    assert len(filtered) == 0


def test_multiple_commits_filtered(config_default_policy):
    """Test that multiple standalone commits are all filtered."""
    from release_tool.models import Commit, PullRequest
    from datetime import datetime

    author = Author(name="Test", username="test", email="test@example.com")

    changes = [
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="a1", repo_id=1, message="Commit 1", author=author, date=datetime.now())],
            prs=[]
        ),
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="a2", repo_id=1, message="Commit 2", author=author, date=datetime.now())],
            prs=[]
        ),
        ConsolidatedChange(
            type="commit",
            commits=[Commit(sha="a3", repo_id=1, message="Commit 3", author=author, date=datetime.now())],
            prs=[]
        ),
        ConsolidatedChange(
            type="pr",
            prs=[PullRequest(repo_id=1, number=1, title="PR 1", state="merged", author=author)],
            commits=[]
        ),
    ]

    filtered = _filter_by_inclusion_policy(changes, config_default_policy, debug=False)

    # Only the PR should remain
    assert len(filtered) == 1
    assert filtered[0].type == "pr"
    assert filtered[0].prs[0].title == "PR 1"
