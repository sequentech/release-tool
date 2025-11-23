"""Tests for database operations."""

import sqlite3
import pytest
from datetime import datetime
from release_tool.db import Database
from release_tool.models import Repository, PullRequest, Commit, Label, Ticket, Release, Author


@pytest.fixture
def db(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.connect()
    yield database
    database.close()


def test_init_db(db):
    """Test database initialization."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    assert "repositories" in tables
    assert "pull_requests" in tables
    assert "commits" in tables
    assert "tickets" in tables
    assert "releases" in tables


def test_upsert_repository(db):
    """Test repository upsert."""
    repo = Repository(owner="test", name="repo", url="http://example.com")
    repo_id = db.upsert_repository(repo)
    assert repo_id is not None

    fetched_repo = db.get_repository("test/repo")
    assert fetched_repo.owner == "test"
    assert fetched_repo.name == "repo"
    assert fetched_repo.url == "http://example.com"


def test_upsert_pull_request(db):
    """Test PR upsert."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    author = Author(name="dev", username="dev")
    pr = PullRequest(
        repo_id=repo_id,
        number=1,
        title="Test PR",
        state="closed",
        merged_at=datetime.now(),
        author=author,
        base_branch="main",
        head_branch="feature",
        head_sha="abc123",
        labels=[Label(name="bug")]
    )

    pr_id = db.upsert_pull_request(pr)
    assert pr_id is not None

    fetched_pr = db.get_pull_request(repo_id, 1)
    assert fetched_pr.title == "Test PR"
    assert fetched_pr.author.name == "dev"
    assert fetched_pr.author.username == "dev"
    assert len(fetched_pr.labels) == 1
    assert fetched_pr.labels[0].name == "bug"


def test_upsert_commit(db):
    """Test commit upsert."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    author = Author(name="dev", email="dev@example.com")
    commit = Commit(
        sha="abc123",
        repo_id=repo_id,
        message="Test commit",
        author=author,
        date=datetime.now()
    )

    db.upsert_commit(commit)

    fetched_commit = db.get_commit("abc123")
    assert fetched_commit.sha == "abc123"
    assert fetched_commit.message == "Test commit"
    assert fetched_commit.author.name == "dev"
    assert fetched_commit.author.email == "dev@example.com"


def test_upsert_ticket(db):
    """Test ticket upsert."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    ticket = Ticket(
        repo_id=repo_id,
        number=123,
        key="#123",
        title="Fix bug",
        state="closed",
        labels=[Label(name="bug")]
    )

    ticket_id = db.upsert_ticket(ticket)
    assert ticket_id is not None

    fetched_ticket = db.get_ticket(repo_id, "#123")
    assert fetched_ticket.title == "Fix bug"
    assert fetched_ticket.number == 123


def test_upsert_release(db):
    """Test release upsert."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    release = Release(
        repo_id=repo_id,
        version="1.0.0",
        tag_name="v1.0.0",
        name="Release 1.0.0",
        is_prerelease=False
    )

    release_id = db.upsert_release(release)
    assert release_id is not None

    fetched_release = db.get_release(repo_id, "1.0.0")
    assert fetched_release.version == "1.0.0"
    assert fetched_release.tag_name == "v1.0.0"


def test_get_all_releases(db):
    """Test fetching all releases."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create multiple releases
    for i in range(3):
        release = Release(
            repo_id=repo_id,
            version=f"1.{i}.0",
            tag_name=f"v1.{i}.0",
            is_prerelease=False
        )
        db.upsert_release(release)

    releases = db.get_all_releases(repo_id)
    assert len(releases) == 3
