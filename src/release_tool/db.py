# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Database operations for the release tool."""

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .models import (
    Repository, PullRequest, Commit, Issue, Release, Label
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

        # Issues table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS issues (
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
                target_commitish TEXT,
                FOREIGN KEY (repo_id) REFERENCES repositories (id),
                UNIQUE(repo_id, version)
            )
        """)

        # Migration for existing tables
        try:
            self.cursor.execute("ALTER TABLE releases ADD COLUMN target_commitish TEXT")
        except sqlite3.OperationalError:
            # Column likely already exists
            pass

        # Migration v1.5: Rename issues table to issues
        try:
            # Check if old issues table exists
            self.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='issues'"
            )
            if self.cursor.fetchone():
                # Rename issues → issues
                self.cursor.execute("ALTER TABLE issues RENAME TO issues")
                print("Database migration: Renamed 'issues' table to 'issues'")
        except sqlite3.OperationalError as e:
            # Table rename might have already happened or issues table already exists
            pass

        # Migration v1.5: Rename release_issues table to release_issues
        try:
            self.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='release_issues'"
            )
            if self.cursor.fetchone():
                self.cursor.execute("ALTER TABLE release_issues RENAME TO release_issues")
                # Rename column issue_number → issue_number
                # SQLite doesn't support ALTER COLUMN RENAME directly, so we need to recreate
                self.cursor.execute("ALTER TABLE release_issues RENAME COLUMN issue_number TO issue_number")
                self.cursor.execute("ALTER TABLE release_issues RENAME COLUMN issue_url TO issue_url")
                print("Database migration: Renamed 'release_issues' table to 'release_issues'")
        except sqlite3.OperationalError as e:
            # Migration might have already happened
            pass

        # Pull metadata table - tracks last pull timestamp per repository
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

        # Release issues table - tracks association between releases and tracking issues
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS release_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_full_name TEXT NOT NULL,
                version TEXT NOT NULL,
                issue_number INTEGER NOT NULL,
                issue_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(repo_full_name, version)
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
            CREATE INDEX IF NOT EXISTS idx_issue_repo
            ON issues(repo_id, state)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_release_issue_repo_version
            ON release_issues(repo_full_name, version)
        """)

        self.conn.commit()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

    # =========================================================================
    # Pull Metadata Methods
    # =========================================================================

    def get_last_pull(self, repo_full_name: str, entity_type: str) -> Optional[datetime]:
        """
        Get the last pull timestamp for a repository and entity type.

        Args:
            repo_full_name: Full repository name (owner/repo)
            entity_type: Type of entity ('issues', 'pull_requests', 'commits')

        Returns:
            Last pull datetime or None if never pulled
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

    def update_pull_metadata(
        self,
        repo_full_name: str,
        entity_type: str,
        cutoff_date: Optional[str] = None,
        total_fetched: int = 0
    ) -> None:
        """
        Update pull metadata for a repository and entity type.

        Args:
            repo_full_name: Full repository name (owner/repo)
            entity_type: Type of entity ('issues', 'pull_requests', 'commits')
            cutoff_date: Optional cutoff date (ISO format)
            total_fetched: Number of items fetched in this pull
        """
        now = datetime.now().isoformat()

        self.cursor.execute(
            """INSERT OR REPLACE INTO sync_metadata
               (repo_full_name, entity_type, last_sync_at, cutoff_date, total_fetched)
               VALUES (?, ?, ?, ?, ?)""",
            (repo_full_name, entity_type, now, cutoff_date, total_fetched)
        )
        self.conn.commit()

    def get_all_pull_status(self) -> List[Dict[str, Any]]:
        """Get pull status for all repositories and entity types."""
        self.cursor.execute(
            """SELECT repo_full_name, entity_type, last_sync_at, cutoff_date, total_fetched
               FROM sync_metadata
               ORDER BY repo_full_name, entity_type"""
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_existing_issue_numbers(self, repo_full_name: str) -> set:
        """Get set of issue numbers already in database for a repository."""
        self.cursor.execute(
            """SELECT t.number FROM issues t
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

    def get_repository_by_id(self, repo_id: int) -> Optional[Repository]:
        """Get repository by ID."""
        self.cursor.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,))
        row = self.cursor.fetchone()
        if row:
            return Repository(**dict(row))
        return None

    def get_all_repositories(self) -> List[Repository]:
        """Get all repositories from the database."""
        self.cursor.execute("SELECT * FROM repositories")
        rows = self.cursor.fetchall()
        return [Repository(**dict(row)) for row in rows]

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

    def find_prs_for_issue(
        self,
        repo_full_name: str,
        issue_number: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find PRs associated with an issue using best-effort search.

        Searches for PRs where body or title contains #issue_number using regex.

        Args:
            repo_full_name: Full repository name (owner/repo)
            issue_number: Issue number to search for
            limit: Maximum number of results to return

        Returns:
            List of dicts with: number, title, url, state, merged_at, head_branch
        """
        import re

        # Get repository
        repo = self.get_repository(repo_full_name)
        if not repo:
            return []

        repo_id = repo.id

        # Get all PRs for the repo (or limit to recent ones)
        self.cursor.execute(
            """SELECT number, title, body, state, url, merged_at, head_branch
               FROM pull_requests
               WHERE repo_id=?
               ORDER BY number DESC
               LIMIT 1000""",  # Limit search to last 1000 PRs for performance
            (repo_id,)
        )
        rows = self.cursor.fetchall()

        # Search for issue references in PR title and body
        pattern = rf'#\s*{issue_number}\b' if issue_number > 0 else r'#'
        matching_prs = []

        for row in rows:
            data = dict(row)
            title = data.get('title', '')
            body = data.get('body', '')

            # Check if pattern matches
            if re.search(pattern, title) or re.search(pattern, body):
                matching_prs.append({
                    'number': data.get('number'),
                    'title': title,
                    'url': data.get('url'),
                    'state': data.get('state'),
                    'merged_at': data.get('merged_at'),
                    'head_branch': data.get('head_branch'),
                    'body': body
                })

                if len(matching_prs) >= limit:
                    break

        return matching_prs

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

    # Issue operations
    def upsert_issue(self, issue: Issue) -> int:
        """Insert or update a issue."""
        labels_json = json.dumps([label.model_dump() for label in issue.labels])
        tags_json = json.dumps(issue.tags)
        created_at_str = issue.created_at.isoformat() if issue.created_at else None
        closed_at_str = issue.closed_at.isoformat() if issue.closed_at else None

        try:
            self.cursor.execute(
                """INSERT INTO issues (
                    repo_id, number, key, title, body, state, labels, url,
                    created_at, closed_at, category, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (issue.repo_id, issue.number, issue.key, issue.title, issue.body,
                 issue.state, labels_json, issue.url, created_at_str, closed_at_str,
                 issue.category, tags_json)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute(
                """UPDATE issues SET
                    number=?, title=?, body=?, state=?, labels=?, url=?,
                    created_at=?, closed_at=?, category=?, tags=?
                WHERE repo_id=? AND key=?""",
                (issue.number, issue.title, issue.body, issue.state, labels_json,
                 issue.url, created_at_str, closed_at_str, issue.category, tags_json,
                 issue.repo_id, issue.key)
            )
            self.conn.commit()
            return self.get_issue_id(issue.repo_id, issue.key)

    def get_issue_id(self, repo_id: int, key: str) -> Optional[int]:
        """Get issue ID by repo and key."""
        self.cursor.execute(
            "SELECT id FROM issues WHERE repo_id=? AND key=?",
            (repo_id, key)
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def get_issue(self, repo_id: int, key: str) -> Optional[Issue]:
        """Get issue by repo and key."""
        self.cursor.execute(
            "SELECT * FROM issues WHERE repo_id=? AND key=?",
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
            return Issue(**data)
        return None

    def get_issue_by_key(self, key: str) -> Optional[Issue]:
        """
        Get issue by key across all repositories.

        This searches for a issue by key without requiring a specific repo_id.
        Useful when the issue could be in any of the configured issue repos.

        Args:
            key: Issue key (e.g., "8624", "#123", "JIRA-456")

        Returns:
            Issue if found, None otherwise
        """
        # Normalize key: strip "#" prefix if present
        normalized_key = key.lstrip('#') if key.startswith('#') else key

        self.cursor.execute(
            "SELECT * FROM issues WHERE key=? ORDER BY created_at DESC LIMIT 1",
            (normalized_key,)
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
            return Issue(**data)
        return None

    def _parse_issue_number(self, key: str) -> Optional[int]:
        """
        Parse numeric portion from a issue key.

        Handles various formats:
        - "8624" -> 8624
        - "#8624" -> 8624
        - "ISSUE-8624" -> 8624
        - "meta-8624" -> 8624

        Args:
            key: Issue key in any format

        Returns:
            Integer issue number if found, None otherwise
        """
        import re
        # Try to find a number in the key
        match = re.search(r'\d+', key)
        if match:
            try:
                return int(match.group())
            except ValueError:
                return None
        return None

    def query_issues(
        self,
        issue_key: Optional[str] = None,
        repo_id: Optional[int] = None,
        repo_full_name: Optional[str] = None,
        starts_with: Optional[str] = None,
        ends_with: Optional[str] = None,
        close_to: Optional[str] = None,
        close_range: int = 10,
        limit: int = 20,
        offset: int = 0
    ) -> List[Issue]:
        """
        Query issues with flexible filtering and fuzzy matching.

        This method supports multiple query patterns:
        - Exact match by issue_key
        - Filter by repository (id or full_name)
        - Fuzzy matching: starts_with, ends_with
        - Proximity search: close_to with configurable range

        Args:
            issue_key: Exact issue key to search for
            repo_id: Filter by repository ID
            repo_full_name: Filter by repository full name (e.g., "owner/repo")
            starts_with: Find issues where key starts with this prefix
            ends_with: Find issues where key ends with this suffix
            close_to: Find issues numerically close to this number
            close_range: Range for close_to search (default: ±10)
            limit: Maximum number of results (default: 20)
            offset: Skip first N results (for pagination)

        Returns:
            List of Issue objects matching the query

        Examples:
            # Find specific issue
            query_issues(issue_key="8624")

            # Find all issues in a repo
            query_issues(repo_full_name="sequentech/meta", limit=50)

            # Fuzzy match: issues starting with "86"
            query_issues(starts_with="86")

            # Find issues close to 8624 (8604-8644)
            query_issues(close_to="8624", close_range=10)
        """
        # Build the SQL query dynamically based on filters
        conditions = []
        params = []

        # Handle repo filter (either by id or full_name)
        if repo_id is not None:
            conditions.append("t.repo_id = ?")
            params.append(repo_id)
        elif repo_full_name is not None:
            # Need to join with repositories table
            conditions.append("r.full_name = ?")
            params.append(repo_full_name)

        # Handle exact issue key
        if issue_key:
            # Normalize key: strip "#" prefix if present
            normalized_key = issue_key.lstrip('#') if issue_key.startswith('#') else issue_key
            conditions.append("t.key = ?")
            params.append(normalized_key)

        # Handle fuzzy matching
        if starts_with:
            conditions.append("(t.key LIKE ? OR CAST(t.number AS TEXT) LIKE ?)")
            params.append(f"{starts_with}%")
            params.append(f"{starts_with}%")

        if ends_with:
            conditions.append("(t.key LIKE ? OR CAST(t.number AS TEXT) LIKE ?)")
            params.append(f"%{ends_with}")
            params.append(f"%{ends_with}")

        # Handle proximity search
        if close_to:
            target_num = self._parse_issue_number(close_to)
            if target_num is not None:
                lower = target_num - close_range
                upper = target_num + close_range
                conditions.append("t.number BETWEEN ? AND ?")
                params.append(lower)
                params.append(upper)

        # Build the WHERE clause
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Build the full query with JOIN to get repo information
        query = f"""
            SELECT
                t.*,
                r.full_name as repo_full_name,
                r.owner as repo_owner,
                r.name as repo_name
            FROM issues t
            LEFT JOIN repositories r ON t.repo_id = r.id
            WHERE {where_clause}
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
        """

        params.extend([limit, offset])

        # Execute query
        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()

        # Parse results into Issue objects with repo info stored separately
        issues = []
        for row in rows:
            data = dict(row)
            # Extract the joined repo fields (not part of Issue model)
            repo_full_name_val = data.pop('repo_full_name', None)
            data.pop('repo_owner', None)
            data.pop('repo_name', None)

            # Parse JSON fields
            data['labels'] = [Label(**l) for l in json.loads(data.get('labels', '[]'))]
            data['tags'] = json.loads(data.get('tags', '{}'))

            # Parse dates
            if data.get('created_at'):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if data.get('closed_at'):
                data['closed_at'] = datetime.fromisoformat(data['closed_at'])

            issue = Issue(**data)
            # Store repo info in a way that won't conflict with Pydantic
            # Use object.__setattr__ to bypass Pydantic's validation
            object.__setattr__(issue, '_repo_full_name', repo_full_name_val)
            issues.append(issue)

        return issues

    # Release operations
    def upsert_release(self, release: Release) -> int:
        """Insert or update a release."""
        created_at_str = release.created_at.isoformat() if release.created_at else None
        published_at_str = release.published_at.isoformat() if release.published_at else None

        try:
            self.cursor.execute(
                """INSERT INTO releases (
                    repo_id, version, tag_name, name, body, created_at, published_at,
                    is_draft, is_prerelease, url, target_commitish
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (release.repo_id, release.version, release.tag_name, release.name,
                 release.body, created_at_str, published_at_str,
                 int(release.is_draft), int(release.is_prerelease), release.url,
                 release.target_commitish)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute(
                """UPDATE releases SET
                    tag_name=?, name=?, body=?, created_at=?, published_at=?,
                    is_draft=?, is_prerelease=?, url=?, target_commitish=?
                WHERE repo_id=? AND version=?""",
                (release.tag_name, release.name, release.body, created_at_str,
                 published_at_str, int(release.is_draft), int(release.is_prerelease),
                 release.url, release.target_commitish, release.repo_id, release.version)
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

    def delete_release(self, repo_id: int, version: str) -> bool:
        """
        Delete a release from the database.

        Args:
            repo_id: Repository ID
            version: Version string

        Returns:
            True if release was deleted or didn't exist, False on error
        """
        try:
            self.cursor.execute(
                "DELETE FROM releases WHERE repo_id=? AND version=?",
                (repo_id, version)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

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
                # Match exact version, version starting with prefix followed by ".", or "-" (for prereleases)
                version_matches = (
                    release.version == version_prefix or
                    release.version.startswith(version_prefix + ".") or
                    release.version.startswith(version_prefix + "-")
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

    def migrate_issue_keys_strip_hash(self) -> int:
        """
        Migrate database: strip "#" prefix from all issue keys.

        This is a one-time migration for version 1.3 which changes the issue key
        storage format from "#8624" to "8624".

        Returns:
            Number of issues updated
        """
        # Update all issue keys that start with #
        self.cursor.execute("""
            UPDATE issues
            SET key = SUBSTR(key, 2)
            WHERE key LIKE '#%'
        """)

        updated_count = self.cursor.rowcount
        self.conn.commit()

        return updated_count

    # Release issue association operations
    def save_issue_association(
        self,
        repo_full_name: str,
        version: str,
        issue_number: int,
        issue_url: str
    ) -> None:
        """
        Save or update the association between a release version and its tracking issue.

        Args:
            repo_full_name: Full repository name (owner/repo)
            version: Release version (e.g., "1.2.3")
            issue_number: GitHub issue number
            issue_url: URL to the GitHub issue

        Example:
            db.save_issue_association(
                repo_full_name="sequentech/step",
                version="1.2.3",
                issue_number=8624,
                issue_url="https://github.com/sequentech/meta/issues/8624"
            )
        """
        now = datetime.now().isoformat()

        self.cursor.execute(
            """INSERT OR REPLACE INTO release_issues
               (repo_full_name, version, issue_number, issue_url, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (repo_full_name, version, issue_number, issue_url, now)
        )
        self.conn.commit()

    def get_issue_association(
        self,
        repo_full_name: str,
        version: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the tracking issue associated with a release version.

        Args:
            repo_full_name: Full repository name (owner/repo)
            version: Release version (e.g., "1.2.3")

        Returns:
            Dictionary with issue_number, issue_url, created_at if found, None otherwise

        Example:
            association = db.get_issue_association("sequentech/step", "1.2.3")
            if association:
                print(f"Issue #{association['issue_number']}: {association['issue_url']}")
        """
        self.cursor.execute(
            """SELECT issue_number, issue_url, created_at
               FROM release_issues
               WHERE repo_full_name=? AND version=?""",
            (repo_full_name, version)
        )
        row = self.cursor.fetchone()
        if row:
            return dict(row)
        return None

    def get_issue_association_by_issue(
        self,
        repo_full_name: str,
        issue_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get the release version associated with a tracking issue.

        Args:
            repo_full_name: Full repository name (owner/repo)
            issue_number: GitHub issue number

        Returns:
            Dictionary with version, issue_url, created_at if found, None otherwise

        Example:
            association = db.get_issue_association_by_issue("sequentech/step", 8624)
            if association:
                print(f"Version {association['version']}: {association['issue_url']}")
        """
        self.cursor.execute(
            """SELECT version, issue_url, created_at
               FROM release_issues
               WHERE repo_full_name=? AND issue_number=?""",
            (repo_full_name, issue_number)
        )
        row = self.cursor.fetchone()
        if row:
            return dict(row)
        return None

    def has_issue_association(self, repo_full_name: str, version: str) -> bool:
        """
        Check if a release version has an associated tracking issue.

        Args:
            repo_full_name: Full repository name (owner/repo)
            version: Release version (e.g., "1.2.3")

        Returns:
            True if association exists, False otherwise

        Example:
            if db.has_issue_association("sequentech/step", "1.2.3"):
                print("This release already has a tracking issue")
        """
        return self.get_issue_association(repo_full_name, version) is not None
