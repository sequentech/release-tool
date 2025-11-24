"""Database operations for the release tool."""

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .models import (
    Repository, PullRequest, Commit, Ticket, Release, Label
)


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: str = "release_tool.db"):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None

    def connect(self):
        """Connect to the database and initialize schema."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._init_db()

    def _init_db(self):
        """Create database schema."""
        # Repositories table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL UNIQUE,
                url TEXT,
                default_branch TEXT DEFAULT 'main'
            )
        """)

        # Authors table - stores unique authors
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS authors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                username TEXT,
                github_id INTEGER,
                display_name TEXT,
                avatar_url TEXT,
                profile_url TEXT,
                company TEXT,
                location TEXT,
                bio TEXT,
                blog TEXT,
                user_type TEXT
            )
        """)

        # Pull requests table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS pull_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                state TEXT,
                merged_at TEXT,
                author_json TEXT,
                base_branch TEXT,
                head_branch TEXT,
                head_sha TEXT,
                labels TEXT,
                url TEXT,
                FOREIGN KEY (repo_id) REFERENCES repositories (id),
                UNIQUE(repo_id, number)
            )
        """)

        # Commits table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS commits (
                sha TEXT PRIMARY KEY,
                repo_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                author_json TEXT NOT NULL,
                date TEXT NOT NULL,
                url TEXT,
                pr_number INTEGER,
                FOREIGN KEY (repo_id) REFERENCES repositories (id)
            )
        """)

        # Tickets/Issues table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                key TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                state TEXT,
                labels TEXT,
                url TEXT,
                created_at TEXT,
                closed_at TEXT,
                category TEXT,
                tags TEXT,
                FOREIGN KEY (repo_id) REFERENCES repositories (id),
                UNIQUE(repo_id, key)
            )
        """)

        # Releases table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER NOT NULL,
                version TEXT NOT NULL,
                tag_name TEXT NOT NULL,
                name TEXT,
                body TEXT,
                created_at TEXT,
                published_at TEXT,
                is_draft INTEGER DEFAULT 0,
                is_prerelease INTEGER DEFAULT 0,
                url TEXT,
                FOREIGN KEY (repo_id) REFERENCES repositories (id),
                UNIQUE(repo_id, version)
            )
        """)

        # Sync metadata table - tracks last sync timestamp per repository
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_full_name TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                last_sync_at TEXT NOT NULL,
                cutoff_date TEXT,
                total_fetched INTEGER DEFAULT 0,
                UNIQUE(repo_full_name, entity_type)
            )
        """)

        # Create indexes for performance
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pr_repo_merged
            ON pull_requests(repo_id, merged_at)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_commit_repo
            ON commits(repo_id, date)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticket_repo
            ON tickets(repo_id, state)
        """)

        self.conn.commit()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

    # =========================================================================
    # Sync Metadata Methods
    # =========================================================================

    def get_last_sync(self, repo_full_name: str, entity_type: str) -> Optional[datetime]:
        """
        Get the last sync timestamp for a repository and entity type.

        Args:
            repo_full_name: Full repository name (owner/repo)
            entity_type: Type of entity ('tickets', 'pull_requests', 'commits')

        Returns:
            Last sync datetime or None if never synced
        """
        self.cursor.execute(
            """SELECT last_sync_at FROM sync_metadata
               WHERE repo_full_name=? AND entity_type=?""",
            (repo_full_name, entity_type)
        )
        row = self.cursor.fetchone()
        if row:
            return datetime.fromisoformat(row['last_sync_at'])
        return None

    def update_sync_metadata(
        self,
        repo_full_name: str,
        entity_type: str,
        cutoff_date: Optional[str] = None,
        total_fetched: int = 0
    ) -> None:
        """
        Update sync metadata for a repository and entity type.

        Args:
            repo_full_name: Full repository name (owner/repo)
            entity_type: Type of entity ('tickets', 'pull_requests', 'commits')
            cutoff_date: Optional cutoff date (ISO format)
            total_fetched: Number of items fetched in this sync
        """
        now = datetime.now().isoformat()

        self.cursor.execute(
            """INSERT OR REPLACE INTO sync_metadata
               (repo_full_name, entity_type, last_sync_at, cutoff_date, total_fetched)
               VALUES (?, ?, ?, ?, ?)""",
            (repo_full_name, entity_type, now, cutoff_date, total_fetched)
        )
        self.conn.commit()

    def get_all_sync_status(self) -> List[Dict[str, Any]]:
        """Get sync status for all repositories and entity types."""
        self.cursor.execute(
            """SELECT repo_full_name, entity_type, last_sync_at, cutoff_date, total_fetched
               FROM sync_metadata
               ORDER BY repo_full_name, entity_type"""
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_existing_ticket_numbers(self, repo_full_name: str) -> set:
        """Get set of ticket numbers already in database for a repository."""
        self.cursor.execute(
            """SELECT t.number FROM tickets t
               JOIN repositories r ON t.repo_id = r.id
               WHERE r.full_name = ?""",
            (repo_full_name,)
        )
        return {row['number'] for row in self.cursor.fetchall()}

    def get_existing_pr_numbers(self, repo_full_name: str) -> set:
        """Get set of PR numbers already in database for a repository."""
        self.cursor.execute(
            """SELECT pr.number FROM pull_requests pr
               JOIN repositories r ON pr.repo_id = r.id
               WHERE r.full_name = ?""",
            (repo_full_name,)
        )
        return {row['number'] for row in self.cursor.fetchall()}

    # Repository operations
    def upsert_repository(self, repo: Repository) -> int:
        """Insert or update a repository."""
        try:
            self.cursor.execute(
                """INSERT INTO repositories (owner, name, full_name, url, default_branch)
                   VALUES (?, ?, ?, ?, ?)""",
                (repo.owner, repo.name, repo.full_name, repo.url, repo.default_branch)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute(
                """UPDATE repositories SET owner=?, name=?, url=?, default_branch=?
                   WHERE full_name=?""",
                (repo.owner, repo.name, repo.url, repo.default_branch, repo.full_name)
            )
            self.conn.commit()
            return self.get_repository_id(repo.full_name)

    def get_repository_id(self, full_name: str) -> Optional[int]:
        """Get repository ID by full name."""
        self.cursor.execute("SELECT id FROM repositories WHERE full_name = ?", (full_name,))
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def get_repository(self, full_name: str) -> Optional[Repository]:
        """Get repository by full name."""
        self.cursor.execute("SELECT * FROM repositories WHERE full_name = ?", (full_name,))
        row = self.cursor.fetchone()
        if row:
            return Repository(**dict(row))
        return None

    # Pull request operations
    def upsert_pull_request(self, pr: PullRequest) -> int:
        """Insert or update a pull request."""
        labels_json = json.dumps([label.model_dump() for label in pr.labels])
        merged_at_str = pr.merged_at.isoformat() if pr.merged_at else None
        author_json = json.dumps(pr.author.model_dump()) if pr.author else None

        try:
            self.cursor.execute(
                """INSERT INTO pull_requests (
                    repo_id, number, title, body, state, merged_at, author_json,
                    base_branch, head_branch, head_sha, labels, url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pr.repo_id, pr.number, pr.title, pr.body, pr.state, merged_at_str,
                 author_json, pr.base_branch, pr.head_branch, pr.head_sha, labels_json, pr.url)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute(
                """UPDATE pull_requests SET
                    title=?, body=?, state=?, merged_at=?, author_json=?,
                    base_branch=?, head_branch=?, head_sha=?, labels=?, url=?
                WHERE repo_id=? AND number=?""",
                (pr.title, pr.body, pr.state, merged_at_str, author_json,
                 pr.base_branch, pr.head_branch, pr.head_sha, labels_json, pr.url,
                 pr.repo_id, pr.number)
            )
            self.conn.commit()
            return self.get_pull_request_id(pr.repo_id, pr.number)

    def get_pull_request_id(self, repo_id: int, number: int) -> Optional[int]:
        """Get PR ID by repo and number."""
        self.cursor.execute(
            "SELECT id FROM pull_requests WHERE repo_id=? AND number=?",
            (repo_id, number)
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def get_pull_request(self, repo_id: int, number: int) -> Optional[PullRequest]:
        """Get pull request by repo and number."""
        from .models import Author

        self.cursor.execute(
            "SELECT * FROM pull_requests WHERE repo_id=? AND number=?",
            (repo_id, number)
        )
        row = self.cursor.fetchone()
        if row:
            data = dict(row)
            data['labels'] = [Label(**l) for l in json.loads(data.get('labels', '[]'))]
            if data.get('merged_at'):
                data['merged_at'] = datetime.fromisoformat(data['merged_at'])
            # Deserialize author from JSON
            if data.get('author_json'):
                data['author'] = Author(**json.loads(data['author_json']))
                del data['author_json']
            return PullRequest(**data)
        return None

    def get_merged_prs_between_dates(
        self, repo_id: int, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> List[PullRequest]:
        """Get merged PRs in a date range."""
        query = "SELECT * FROM pull_requests WHERE repo_id=? AND merged_at IS NOT NULL"
        params = [repo_id]

        if start_date:
            query += " AND merged_at >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND merged_at <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY merged_at ASC"

        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()

        from .models import Author

        prs = []
        for row in rows:
            data = dict(row)
            data['labels'] = [Label(**l) for l in json.loads(data.get('labels', '[]'))]
            if data.get('merged_at'):
                data['merged_at'] = datetime.fromisoformat(data['merged_at'])
            # Deserialize author from JSON
            if data.get('author_json'):
                data['author'] = Author(**json.loads(data['author_json']))
                del data['author_json']
            prs.append(PullRequest(**data))

        return prs

    # Commit operations
    def upsert_commit(self, commit: Commit) -> None:
        """Insert or update a commit."""
        import json
        date_str = commit.date.isoformat()
        author_json = json.dumps(commit.author.model_dump())

        self.cursor.execute(
            """INSERT OR REPLACE INTO commits (
                sha, repo_id, message, author_json, date, url, pr_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (commit.sha, commit.repo_id, commit.message, author_json,
             date_str, commit.url, commit.pr_number)
        )
        self.conn.commit()

    def get_commit(self, sha: str) -> Optional[Commit]:
        """Get commit by SHA."""
        import json
        from .models import Author

        self.cursor.execute("SELECT * FROM commits WHERE sha=?", (sha,))
        row = self.cursor.fetchone()
        if row:
            data = dict(row)
            data['date'] = datetime.fromisoformat(data['date'])
            # Deserialize author from JSON
            if 'author_json' in data:
                data['author'] = Author(**json.loads(data['author_json']))
                del data['author_json']
            return Commit(**data)
        return None

    def get_commits_by_repo(self, repo_id: int) -> List[Commit]:
        """Get all commits for a repository."""
        import json
        from .models import Author

        self.cursor.execute(
            "SELECT * FROM commits WHERE repo_id=? ORDER BY date ASC",
            (repo_id,)
        )
        rows = self.cursor.fetchall()

        commits = []
        for row in rows:
            data = dict(row)
            data['date'] = datetime.fromisoformat(data['date'])
            # Deserialize author from JSON
            if 'author_json' in data:
                data['author'] = Author(**json.loads(data['author_json']))
                del data['author_json']
            commits.append(Commit(**data))

        return commits

    # Ticket operations
    def upsert_ticket(self, ticket: Ticket) -> int:
        """Insert or update a ticket."""
        labels_json = json.dumps([label.model_dump() for label in ticket.labels])
        tags_json = json.dumps(ticket.tags)
        created_at_str = ticket.created_at.isoformat() if ticket.created_at else None
        closed_at_str = ticket.closed_at.isoformat() if ticket.closed_at else None

        try:
            self.cursor.execute(
                """INSERT INTO tickets (
                    repo_id, number, key, title, body, state, labels, url,
                    created_at, closed_at, category, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticket.repo_id, ticket.number, ticket.key, ticket.title, ticket.body,
                 ticket.state, labels_json, ticket.url, created_at_str, closed_at_str,
                 ticket.category, tags_json)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute(
                """UPDATE tickets SET
                    number=?, title=?, body=?, state=?, labels=?, url=?,
                    created_at=?, closed_at=?, category=?, tags=?
                WHERE repo_id=? AND key=?""",
                (ticket.number, ticket.title, ticket.body, ticket.state, labels_json,
                 ticket.url, created_at_str, closed_at_str, ticket.category, tags_json,
                 ticket.repo_id, ticket.key)
            )
            self.conn.commit()
            return self.get_ticket_id(ticket.repo_id, ticket.key)

    def get_ticket_id(self, repo_id: int, key: str) -> Optional[int]:
        """Get ticket ID by repo and key."""
        self.cursor.execute(
            "SELECT id FROM tickets WHERE repo_id=? AND key=?",
            (repo_id, key)
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def get_ticket(self, repo_id: int, key: str) -> Optional[Ticket]:
        """Get ticket by repo and key."""
        self.cursor.execute(
            "SELECT * FROM tickets WHERE repo_id=? AND key=?",
            (repo_id, key)
        )
        row = self.cursor.fetchone()
        if row:
            data = dict(row)
            data['labels'] = [Label(**l) for l in json.loads(data.get('labels', '[]'))]
            data['tags'] = json.loads(data.get('tags', '{}'))
            if data.get('created_at'):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if data.get('closed_at'):
                data['closed_at'] = datetime.fromisoformat(data['closed_at'])
            return Ticket(**data)
        return None

    # Release operations
    def upsert_release(self, release: Release) -> int:
        """Insert or update a release."""
        created_at_str = release.created_at.isoformat() if release.created_at else None
        published_at_str = release.published_at.isoformat() if release.published_at else None

        try:
            self.cursor.execute(
                """INSERT INTO releases (
                    repo_id, version, tag_name, name, body, created_at, published_at,
                    is_draft, is_prerelease, url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (release.repo_id, release.version, release.tag_name, release.name,
                 release.body, created_at_str, published_at_str,
                 int(release.is_draft), int(release.is_prerelease), release.url)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute(
                """UPDATE releases SET
                    tag_name=?, name=?, body=?, created_at=?, published_at=?,
                    is_draft=?, is_prerelease=?, url=?
                WHERE repo_id=? AND version=?""",
                (release.tag_name, release.name, release.body, created_at_str,
                 published_at_str, int(release.is_draft), int(release.is_prerelease),
                 release.url, release.repo_id, release.version)
            )
            self.conn.commit()
            return self.get_release_id(release.repo_id, release.version)

    def get_release_id(self, repo_id: int, version: str) -> Optional[int]:
        """Get release ID by repo and version."""
        self.cursor.execute(
            "SELECT id FROM releases WHERE repo_id=? AND version=?",
            (repo_id, version)
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def get_release(self, repo_id: int, version: str) -> Optional[Release]:
        """Get release by repo and version."""
        self.cursor.execute(
            "SELECT * FROM releases WHERE repo_id=? AND version=?",
            (repo_id, version)
        )
        row = self.cursor.fetchone()
        if row:
            data = dict(row)
            data['is_draft'] = bool(data['is_draft'])
            data['is_prerelease'] = bool(data['is_prerelease'])
            if data.get('created_at'):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if data.get('published_at'):
                data['published_at'] = datetime.fromisoformat(data['published_at'])
            return Release(**data)
        return None

    def get_all_releases(
        self,
        repo_id: int,
        limit: Optional[int] = None,
        version_prefix: Optional[str] = None,
        release_types: Optional[List[str]] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        # Deprecated parameters - kept for backwards compatibility
        since: Optional[datetime] = None,
        final_only: bool = False
    ) -> List[Release]:
        """
        Get releases for a repository with optional filtering.

        Args:
            repo_id: Repository ID
            limit: Maximum number of releases to return (None for all)
            version_prefix: Filter by version prefix (e.g., "9" for 9.x.x, "9.3" for 9.3.x)
            release_types: List of release types to include ('final', 'rc', 'beta', 'alpha')
            after: Only return releases published after this date
            before: Only return releases published before this date
            since: (Deprecated) Use 'after' instead
            final_only: (Deprecated) Use release_types=['final'] instead

        Returns:
            List of releases ordered by published_at DESC
        """
        from .models import SemanticVersion

        # Handle deprecated parameters
        if since and not after:
            after = since
        if final_only and not release_types:
            release_types = ['final']

        # Build query with filters
        query = "SELECT * FROM releases WHERE repo_id=?"
        params = [repo_id]

        # Date range filters
        if after:
            query += " AND published_at >= ?"
            params.append(after.isoformat())

        if before:
            query += " AND published_at <= ?"
            params.append(before.isoformat())

        query += " ORDER BY published_at DESC"

        # Don't apply LIMIT in SQL if we have client-side filters
        # (version_prefix or release_types) because limit would be applied before filtering
        apply_limit_in_sql = limit and not version_prefix and not release_types

        if apply_limit_in_sql:
            query += " LIMIT ?"
            params.append(limit)

        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()

        releases = []
        for row in rows:
            data = dict(row)
            data['is_draft'] = bool(data['is_draft'])
            data['is_prerelease'] = bool(data['is_prerelease'])
            if data.get('created_at'):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if data.get('published_at'):
                data['published_at'] = datetime.fromisoformat(data['published_at'])

            release = Release(**data)

            # Apply version prefix filter (client-side since version format varies)
            if version_prefix:
                # Match exact version or version starting with prefix followed by "."
                version_matches = (
                    release.version == version_prefix or
                    release.version.startswith(version_prefix + ".")
                )
                if not version_matches:
                    continue

            # Apply release type filter (client-side)
            if release_types:
                try:
                    sem_ver = SemanticVersion.parse(release.version)
                    release_type = sem_ver.get_type()

                    # Map release type to filter values
                    if release_type == 'final' and 'final' not in release_types:
                        continue
                    elif release_type == 'rc' and 'rc' not in release_types:
                        continue
                    elif release_type == 'beta' and 'beta' not in release_types:
                        continue
                    elif release_type == 'alpha' and 'alpha' not in release_types:
                        continue
                except ValueError:
                    # Skip releases with invalid version format
                    continue

            releases.append(release)

            # Apply limit after client-side filtering
            if not apply_limit_in_sql and limit and len(releases) >= limit:
                break

        return releases
