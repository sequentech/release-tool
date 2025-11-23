"""Tests for data models."""

import pytest
from datetime import datetime
from release_tool.models import (
    SemanticVersion, Repository, Label, PullRequest, Commit,
    Ticket, Release, ReleaseNote, VersionType, Author
)


class TestSemanticVersion:
    """Tests for SemanticVersion model."""

    def test_parse_simple_version(self):
        version = SemanticVersion.parse("1.2.3")
        assert version.major == 1
        assert version.minor == 2
        assert version.patch == 3
        assert version.prerelease is None

    def test_parse_version_with_v_prefix(self):
        version = SemanticVersion.parse("v2.0.0")
        assert version.major == 2
        assert version.minor == 0
        assert version.patch == 0

    def test_parse_prerelease_version(self):
        version = SemanticVersion.parse("1.0.0-rc.1")
        assert version.major == 1
        assert version.minor == 0
        assert version.patch == 0
        assert version.prerelease == "rc.1"

    def test_parse_invalid_version(self):
        with pytest.raises(ValueError):
            SemanticVersion.parse("invalid")

    def test_to_string(self):
        version = SemanticVersion(major=1, minor=2, patch=3)
        assert version.to_string() == "1.2.3"

    def test_to_string_with_v(self):
        version = SemanticVersion(major=1, minor=2, patch=3)
        assert version.to_string(include_v=True) == "v1.2.3"

    def test_to_string_with_prerelease(self):
        version = SemanticVersion(major=1, minor=0, patch=0, prerelease="rc.1")
        assert version.to_string() == "1.0.0-rc.1"

    def test_is_final(self):
        final_version = SemanticVersion(major=1, minor=0, patch=0)
        rc_version = SemanticVersion(major=1, minor=0, patch=0, prerelease="rc.1")

        assert final_version.is_final()
        assert not rc_version.is_final()

    def test_get_type(self):
        final = SemanticVersion(major=1, minor=0, patch=0)
        rc = SemanticVersion(major=1, minor=0, patch=0, prerelease="rc.1")
        beta = SemanticVersion(major=1, minor=0, patch=0, prerelease="beta.1")
        alpha = SemanticVersion(major=1, minor=0, patch=0, prerelease="alpha.1")

        assert final.get_type() == VersionType.FINAL
        assert rc.get_type() == VersionType.RELEASE_CANDIDATE
        assert beta.get_type() == VersionType.BETA
        assert alpha.get_type() == VersionType.ALPHA

    def test_comparison_same_version(self):
        v1 = SemanticVersion(major=1, minor=0, patch=0)
        v2 = SemanticVersion(major=1, minor=0, patch=0)
        assert v1 == v2
        assert not v1 < v2
        assert not v1 > v2

    def test_comparison_different_versions(self):
        v1 = SemanticVersion(major=1, minor=0, patch=0)
        v2 = SemanticVersion(major=2, minor=0, patch=0)
        assert v1 < v2
        assert v2 > v1

    def test_comparison_with_prerelease(self):
        final = SemanticVersion(major=1, minor=0, patch=0)
        rc = SemanticVersion(major=1, minor=0, patch=0, prerelease="rc.1")
        assert rc < final
        assert final > rc


class TestRepository:
    """Tests for Repository model."""

    def test_create_repository(self):
        repo = Repository(owner="test", name="repo")
        assert repo.owner == "test"
        assert repo.name == "repo"
        assert repo.full_name == "test/repo"

    def test_repository_with_full_name(self):
        repo = Repository(owner="test", name="repo", full_name="test/repo")
        assert repo.full_name == "test/repo"


class TestPullRequest:
    """Tests for PullRequest model."""

    def test_create_pull_request(self):
        pr = PullRequest(
            repo_id=1,
            number=123,
            title="Test PR",
            state="closed",
            merged_at=datetime.now()
        )
        assert pr.number == 123
        assert pr.title == "Test PR"
        assert pr.state == "closed"


class TestCommit:
    """Tests for Commit model."""

    def test_create_commit(self):
        author = Author(name="John Doe", email="john@example.com")
        commit = Commit(
            sha="abc123",
            repo_id=1,
            message="Test commit",
            author=author,
            date=datetime.now()
        )
        assert commit.sha == "abc123"
        assert commit.message == "Test commit"
        assert commit.author.name == "John Doe"
        assert commit.author.email == "john@example.com"


class TestTicket:
    """Tests for Ticket model."""

    def test_create_ticket(self):
        ticket = Ticket(
            repo_id=1,
            number=456,
            key="#456",
            title="Fix bug",
            state="closed",
            labels=[Label(name="bug")]
        )
        assert ticket.number == 456
        assert ticket.key == "#456"
        assert ticket.title == "Fix bug"
        assert len(ticket.labels) == 1
        assert ticket.labels[0].name == "bug"


class TestRelease:
    """Tests for Release model."""

    def test_create_release(self):
        release = Release(
            repo_id=1,
            version="1.0.0",
            tag_name="v1.0.0",
            is_prerelease=False
        )
        assert release.version == "1.0.0"
        assert release.tag_name == "v1.0.0"
        assert not release.is_prerelease


class TestReleaseNote:
    """Tests for ReleaseNote model."""

    def test_create_release_note(self):
        author1 = Author(name="dev1", username="dev1")
        author2 = Author(name="dev2", username="dev2")
        note = ReleaseNote(
            ticket_key="#123",
            title="Add new feature",
            category="Features",
            authors=[author1, author2],
            pr_numbers=[456]
        )
        assert note.ticket_key == "#123"
        assert note.title == "Add new feature"
        assert note.category == "Features"
        assert len(note.authors) == 2
        assert note.authors[0].name == "dev1"
        assert note.authors[1].name == "dev2"
        assert 456 in note.pr_numbers
