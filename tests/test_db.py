# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for database operations."""

import sqlite3
import pytest
from datetime import datetime
from release_tool.db import Database
from release_tool.models import Repository, PullRequest, Commit, Label, Issue, Release, Author


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
    assert "issues" in tables
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


def test_upsert_issue(db):
    """Test issue upsert."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    issue = Issue(
        repo_id=repo_id,
        number=123,
        key="#123",
        title="Fix bug",
        state="closed",
        labels=[Label(name="bug")]
    )

    issue_id = db.upsert_issue(issue)
    assert issue_id is not None

    fetched_issue = db.get_issue(repo_id, "#123")
    assert fetched_issue.title == "Fix bug"
    assert fetched_issue.number == 123


def test_get_issue_by_key(db):
    """Test getting issue by key across all repos."""
    # Create two different repos (simulating code repo and issue repo)
    code_repo = Repository(owner="org", name="code")
    code_repo_id = db.upsert_repository(code_repo)

    issue_repo = Repository(owner="org", name="issues")
    issue_repo_id = db.upsert_repository(issue_repo)

    # Create issue in issue repo
    issue = Issue(
        repo_id=issue_repo_id,
        number=8624,
        key="8624",  # Bare number as extracted from branch
        title="Implement feature X",
        state="closed",
        labels=[Label(name="enhancement")]
    )
    db.upsert_issue(issue)

    # Query by repo_id should fail when using wrong repo
    wrong_issue = db.get_issue(code_repo_id, "8624")
    assert wrong_issue is None

    # Query by key only should succeed
    found_issue = db.get_issue_by_key("8624")
    assert found_issue is not None
    assert found_issue.title == "Implement feature X"
    assert found_issue.number == 8624
    assert found_issue.repo_id == issue_repo_id


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


def test_get_all_releases_with_limit(db):
    """Test fetching releases with limit."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create 15 releases
    for i in range(15):
        release = Release(
            repo_id=repo_id,
            version=f"1.{i}.0",
            tag_name=f"v1.{i}.0",
            is_prerelease=False,
            published_at=datetime(2024, 1, i + 1)
        )
        db.upsert_release(release)

    # Test limit
    releases = db.get_all_releases(repo_id, limit=10)
    assert len(releases) == 10

    # Test limit=5
    releases = db.get_all_releases(repo_id, limit=5)
    assert len(releases) == 5

    # Test no limit (all)
    releases = db.get_all_releases(repo_id, limit=None)
    assert len(releases) == 15


def test_get_all_releases_with_since_date(db):
    """Test fetching releases filtered by date."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create releases across different dates
    releases_data = [
        ("1.0.0", datetime(2024, 1, 1)),
        ("1.1.0", datetime(2024, 2, 1)),
        ("1.2.0", datetime(2024, 3, 1)),
        ("1.3.0", datetime(2024, 4, 1)),
        ("1.4.0", datetime(2024, 5, 1)),
    ]

    for version, published_at in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=False,
            published_at=published_at
        )
        db.upsert_release(release)

    # Test since March 1st - should get 3 releases (March, April, May)
    releases = db.get_all_releases(repo_id, since=datetime(2024, 3, 1))
    assert len(releases) == 3
    assert releases[0].version == "1.4.0"  # Most recent first
    assert releases[1].version == "1.3.0"
    assert releases[2].version == "1.2.0"

    # Test since April 15th - should get 1 release (May)
    releases = db.get_all_releases(repo_id, since=datetime(2024, 4, 15))
    assert len(releases) == 1
    assert releases[0].version == "1.4.0"


def test_get_all_releases_final_only(db):
    """Test fetching only final releases (excluding prereleases)."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create mix of final and prerelease versions
    releases_data = [
        ("1.0.0", False),      # Final
        ("1.1.0-rc.1", True),  # RC
        ("1.1.0-rc.2", True),  # RC
        ("1.1.0", False),      # Final
        ("2.0.0-beta.1", True),# Beta
        ("2.0.0-rc.1", True),  # RC
        ("2.0.0", False),      # Final
    ]

    for version, is_prerelease in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=is_prerelease,
            published_at=datetime(2024, 1, 1)
        )
        db.upsert_release(release)

    # Test final_only=True - should get only 3 final releases
    releases = db.get_all_releases(repo_id, final_only=True)
    assert len(releases) == 3
    assert all(not r.is_prerelease for r in releases)
    versions = [r.version for r in releases]
    assert "1.0.0" in versions
    assert "1.1.0" in versions
    assert "2.0.0" in versions
    assert "1.1.0-rc.1" not in versions
    assert "2.0.0-beta.1" not in versions

    # Test final_only=False - should get all 7 releases
    releases = db.get_all_releases(repo_id, final_only=False)
    assert len(releases) == 7


def test_get_all_releases_combined_filters(db):
    """Test fetching releases with multiple filters combined."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create releases across dates with mix of final/prerelease
    releases_data = [
        ("1.0.0", False, datetime(2024, 1, 1)),
        ("1.1.0-rc.1", True, datetime(2024, 2, 1)),
        ("1.1.0", False, datetime(2024, 2, 15)),
        ("1.2.0-rc.1", True, datetime(2024, 3, 1)),
        ("1.2.0", False, datetime(2024, 3, 15)),
        ("2.0.0-beta.1", True, datetime(2024, 4, 1)),
        ("2.0.0-rc.1", True, datetime(2024, 4, 15)),
        ("2.0.0", False, datetime(2024, 5, 1)),
    ]

    for version, is_prerelease, published_at in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=is_prerelease,
            published_at=published_at
        )
        db.upsert_release(release)

    # Test: final_only + since Feb 1 + limit 2
    # Should get: 2.0.0, 1.2.0 (most recent 2 finals since Feb 1)
    releases = db.get_all_releases(
        repo_id,
        limit=2,
        since=datetime(2024, 2, 1),
        final_only=True
    )
    assert len(releases) == 2
    assert releases[0].version == "2.0.0"
    assert releases[1].version == "1.2.0"
    assert all(not r.is_prerelease for r in releases)

    # Test: final_only + since April 1
    # Should get: 2.0.0 (only final after April 1)
    releases = db.get_all_releases(
        repo_id,
        since=datetime(2024, 4, 1),
        final_only=True
    )
    assert len(releases) == 1
    assert releases[0].version == "2.0.0"


def test_get_all_releases_ordering(db):
    """Test that releases are ordered by published_at DESC."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create releases in non-chronological order
    releases_data = [
        ("1.0.0", datetime(2024, 1, 1)),
        ("1.2.0", datetime(2024, 3, 1)),
        ("1.1.0", datetime(2024, 2, 1)),
    ]

    for version, published_at in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=False,
            published_at=published_at
        )
        db.upsert_release(release)

    releases = db.get_all_releases(repo_id)

    # Should be ordered newest first
    assert len(releases) == 3
    assert releases[0].version == "1.2.0"  # March (newest)
    assert releases[1].version == "1.1.0"  # February
    assert releases[2].version == "1.0.0"  # January (oldest)


def test_get_all_releases_with_version_prefix(db):
    """Test filtering by version prefix (major or major.minor)."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create releases with different major versions
    releases_data = [
        "8.5.0",
        "9.0.0",
        "9.1.0",
        "9.1.1",
        "9.2.0",
        "9.3.0",
        "9.3.1",
        "9.3.2",
        "10.0.0",
        "10.1.0",
    ]

    for version in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=False,
            published_at=datetime(2024, 1, 1)
        )
        db.upsert_release(release)

    # Test filtering by major version "9"
    releases = db.get_all_releases(repo_id, version_prefix="9")
    assert len(releases) == 7  # 9.0.0, 9.1.0, 9.1.1, 9.2.0, 9.3.0, 9.3.1, 9.3.2
    versions = [r.version for r in releases]
    assert "9.0.0" in versions
    assert "9.3.2" in versions
    assert "8.5.0" not in versions
    assert "10.0.0" not in versions

    # Test filtering by major.minor "9.3"
    releases = db.get_all_releases(repo_id, version_prefix="9.3")
    assert len(releases) == 3
    versions = [r.version for r in releases]
    assert "9.3.0" in versions
    assert "9.3.1" in versions
    assert "9.3.2" in versions
    assert "9.1.0" not in versions
    assert "9.2.0" not in versions

    # Test filtering by major "10"
    releases = db.get_all_releases(repo_id, version_prefix="10")
    assert len(releases) == 2
    versions = [r.version for r in releases]
    assert "10.0.0" in versions
    assert "10.1.0" in versions


def test_get_all_releases_with_release_types(db):
    """Test filtering by release types (final, rc, beta, alpha)."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create mix of different release types
    releases_data = [
        ("9.0.0", False),            # Final
        ("9.1.0-alpha.1", True),     # Alpha
        ("9.1.0-beta.1", True),      # Beta
        ("9.1.0-rc.1", True),        # RC
        ("9.1.0-rc.2", True),        # RC
        ("9.1.0", False),            # Final
        ("9.2.0-alpha.1", True),     # Alpha
        ("9.2.0-beta.1", True),      # Beta
        ("9.2.0-rc.1", True),        # RC
        ("9.2.0", False),            # Final
    ]

    for version, is_prerelease in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=is_prerelease,
            published_at=datetime(2024, 1, 1)
        )
        db.upsert_release(release)

    # Test only final releases
    releases = db.get_all_releases(repo_id, release_types=['final'])
    assert len(releases) == 3
    versions = [r.version for r in releases]
    assert "9.0.0" in versions
    assert "9.1.0" in versions
    assert "9.2.0" in versions

    # Test only RCs
    releases = db.get_all_releases(repo_id, release_types=['rc'])
    assert len(releases) == 3
    versions = [r.version for r in releases]
    assert "9.1.0-rc.1" in versions
    assert "9.1.0-rc.2" in versions
    assert "9.2.0-rc.1" in versions

    # Test finals and RCs
    releases = db.get_all_releases(repo_id, release_types=['final', 'rc'])
    assert len(releases) == 6

    # Test betas and alphas
    releases = db.get_all_releases(repo_id, release_types=['beta', 'alpha'])
    assert len(releases) == 4
    versions = [r.version for r in releases]
    assert "9.1.0-alpha.1" in versions
    assert "9.1.0-beta.1" in versions
    assert "9.2.0-alpha.1" in versions
    assert "9.2.0-beta.1" in versions


def test_get_all_releases_with_date_range(db):
    """Test filtering by date range (after and before)."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create releases across different months
    releases_data = [
        ("1.0.0", datetime(2024, 1, 15)),
        ("1.1.0", datetime(2024, 2, 15)),
        ("1.2.0", datetime(2024, 3, 15)),
        ("1.3.0", datetime(2024, 4, 15)),
        ("1.4.0", datetime(2024, 5, 15)),
        ("1.5.0", datetime(2024, 6, 15)),
    ]

    for version, published_at in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=False,
            published_at=published_at
        )
        db.upsert_release(release)

    # Test after March 1
    releases = db.get_all_releases(repo_id, after=datetime(2024, 3, 1))
    assert len(releases) == 4  # March, April, May, June
    versions = [r.version for r in releases]
    assert "1.2.0" in versions
    assert "1.5.0" in versions
    assert "1.0.0" not in versions

    # Test before April 1
    releases = db.get_all_releases(repo_id, before=datetime(2024, 4, 1))
    assert len(releases) == 3  # Jan, Feb, March
    versions = [r.version for r in releases]
    assert "1.0.0" in versions
    assert "1.2.0" in versions
    assert "1.3.0" not in versions

    # Test date range: March to May
    releases = db.get_all_releases(
        repo_id,
        after=datetime(2024, 3, 1),
        before=datetime(2024, 5, 31)
    )
    assert len(releases) == 3  # March, April, May
    versions = [r.version for r in releases]
    assert "1.2.0" in versions
    assert "1.3.0" in versions
    assert "1.4.0" in versions
    assert "1.5.0" not in versions


def test_get_all_releases_combined_advanced_filters(db):
    """Test combining multiple new filter types."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create complex dataset
    releases_data = [
        ("8.5.0", False, datetime(2024, 1, 1)),
        ("9.0.0", False, datetime(2024, 2, 1)),
        ("9.1.0-rc.1", True, datetime(2024, 3, 1)),
        ("9.1.0", False, datetime(2024, 3, 15)),
        ("9.2.0-beta.1", True, datetime(2024, 4, 1)),
        ("9.2.0-rc.1", True, datetime(2024, 4, 15)),
        ("9.2.0", False, datetime(2024, 5, 1)),
        ("9.3.0-rc.1", True, datetime(2024, 5, 15)),
        ("9.3.0", False, datetime(2024, 6, 1)),
        ("10.0.0-rc.1", True, datetime(2024, 6, 15)),
        ("10.0.0", False, datetime(2024, 7, 1)),
    ]

    for version, is_prerelease, published_at in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=is_prerelease,
            published_at=published_at
        )
        db.upsert_release(release)

    # Test: version 9.x + final only + after March 1
    releases = db.get_all_releases(
        repo_id,
        version_prefix="9",
        release_types=['final'],
        after=datetime(2024, 3, 1)
    )
    assert len(releases) == 3  # 9.1.0, 9.2.0, 9.3.0
    versions = [r.version for r in releases]
    assert "9.1.0" in versions
    assert "9.2.0" in versions
    assert "9.3.0" in versions
    assert "9.0.0" not in versions  # Before March
    assert "10.0.0" not in versions  # Version 10

    # Test: version 9.2.x + all types + limit 2
    releases = db.get_all_releases(
        repo_id,
        version_prefix="9.2",
        limit=2
    )
    assert len(releases) == 2
    # Most recent first
    assert releases[0].version == "9.2.0"
    assert releases[1].version == "9.2.0-rc.1"

    # Test: RCs only + date range
    releases = db.get_all_releases(
        repo_id,
        release_types=['rc'],
        after=datetime(2024, 3, 1),
        before=datetime(2024, 6, 1)
    )
    assert len(releases) == 3  # 9.1.0-rc.1, 9.2.0-rc.1, 9.3.0-rc.1
    versions = [r.version for r in releases]
    assert "9.1.0-rc.1" in versions
    assert "9.2.0-rc.1" in versions
    assert "9.3.0-rc.1" in versions
    assert "10.0.0-rc.1" not in versions  # After June 1


def test_get_all_releases_backwards_compatibility(db):
    """Test that deprecated parameters still work."""
    repo = Repository(owner="test", name="repo")
    repo_id = db.upsert_repository(repo)

    # Create test data
    releases_data = [
        ("1.0.0", False, datetime(2024, 1, 1)),
        ("1.1.0-rc.1", True, datetime(2024, 2, 1)),
        ("1.1.0", False, datetime(2024, 3, 1)),
    ]

    for version, is_prerelease, published_at in releases_data:
        release = Release(
            repo_id=repo_id,
            version=version,
            tag_name=f"v{version}",
            is_prerelease=is_prerelease,
            published_at=published_at
        )
        db.upsert_release(release)

    # Test deprecated final_only parameter
    releases = db.get_all_releases(repo_id, final_only=True)
    assert len(releases) == 2
    versions = [r.version for r in releases]
    assert "1.0.0" in versions
    assert "1.1.0" in versions

    # Test deprecated since parameter
    releases = db.get_all_releases(repo_id, since=datetime(2024, 2, 1))
    assert len(releases) == 2
    assert releases[0].version == "1.1.0"
    assert releases[1].version == "1.1.0-rc.1"
