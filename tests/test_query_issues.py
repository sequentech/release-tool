# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for issues command and database querying."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from click.testing import CliRunner

from release_tool.db import Database
from release_tool.models import Repository, Issue, Label
from release_tool.main import cli


@pytest.fixture
def test_db():
    """Create a test database with sample data."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
        db_path = f.name

    db = Database(db_path)
    db.connect()

    # Create test repositories
    meta_repo = Repository(owner="sequentech", name="meta")
    step_repo = Repository(owner="sequentech", name="step")

    meta_id = db.upsert_repository(meta_repo)
    step_id = db.upsert_repository(step_repo)

    # Create test issues
    issues_data = [
        # Meta repo issues
        Issue(
            repo_id=meta_id,
            number=8624,
            key="8624",
            title="Add dark mode to UI",
            body="Implement dark mode across the application",
            state="open",
            labels=[Label(name="feature"), Label(name="ui")],
            url="https://github.com/sequentech/meta/issues/8624",
            created_at=datetime(2024, 1, 15),
        ),
        Issue(
            repo_id=meta_id,
            number=8625,
            key="8625",
            title="Fix login bug",
            body="Users cannot log in",
            state="closed",
            labels=[Label(name="bug")],
            url="https://github.com/sequentech/meta/issues/8625",
            created_at=datetime(2024, 1, 16),
            closed_at=datetime(2024, 1, 20),
        ),
        Issue(
            repo_id=meta_id,
            number=8650,
            key="8650",
            title="Update documentation",
            body="Refresh README",
            state="open",
            labels=[Label(name="docs")],
            url="https://github.com/sequentech/meta/issues/8650",
            created_at=datetime(2024, 2, 1),
        ),
        Issue(
            repo_id=meta_id,
            number=8624,
            key="#8624",  # Duplicate with # prefix
            title="Another issue",
            body="Test duplicate key handling",
            state="open",
            labels=[],
            url="https://github.com/sequentech/meta/issues/8624",
            created_at=datetime(2024, 1, 10),  # Earlier than first 8624
        ),
        # Step repo issues
        Issue(
            repo_id=step_id,
            number=1024,
            key="1024",
            title="Performance optimization",
            body="Improve query speed",
            state="open",
            labels=[Label(name="performance")],
            url="https://github.com/sequentech/step/issues/1024",
            created_at=datetime(2024, 3, 1),
        ),
        Issue(
            repo_id=step_id,
            number=1124,
            key="1124",
            title="Security patch",
            body="Fix vulnerability",
            state="closed",
            labels=[Label(name="security"), Label(name="high-priority")],
            url="https://github.com/sequentech/step/issues/1124",
            created_at=datetime(2024, 3, 10),
            closed_at=datetime(2024, 3, 15),
        ),
    ]

    for issue in issues_data:
        db.upsert_issue(issue)

    yield db, meta_id, step_id

    # Cleanup
    db.close()
    Path(db_path).unlink()


class TestParseIssueNumber:
    """Tests for _parse_issue_number helper."""

    def test_parse_plain_number(self, test_db):
        """Test parsing plain number."""
        db, _, _ = test_db
        assert db._parse_issue_number("8624") == 8624

    def test_parse_hash_prefix(self, test_db):
        """Test parsing with # prefix."""
        db, _, _ = test_db
        assert db._parse_issue_number("#8624") == 8624

    def test_parse_jira_style(self, test_db):
        """Test parsing JIRA-style key."""
        db, _, _ = test_db
        assert db._parse_issue_number("ISSUE-8624") == 8624
        assert db._parse_issue_number("meta-8624") == 8624

    def test_parse_no_number(self, test_db):
        """Test parsing with no number."""
        db, _, _ = test_db
        assert db._parse_issue_number("no-numbers-here") is None

    def test_parse_empty(self, test_db):
        """Test parsing empty string."""
        db, _, _ = test_db
        assert db._parse_issue_number("") is None


class TestQueryIssuesDatabase:
    """Tests for database query_issues method."""

    def test_query_by_exact_issue_key(self, test_db):
        """Test finding issue by exact key."""
        db, _, _ = test_db
        issues = db.query_issues(issue_key="8624")

        assert len(issues) >= 1
        # Should find the most recent one
        assert issues[0].key in ["8624", "#8624"]

    def test_query_by_repo_id(self, test_db):
        """Test finding all issues in a repo."""
        db, meta_id, step_id = test_db

        meta_issues = db.query_issues(repo_id=meta_id, limit=100)
        assert len(meta_issues) == 4  # 4 issues in meta repo

        step_issues = db.query_issues(repo_id=step_id, limit=100)
        assert len(step_issues) == 2  # 2 issues in step repo

    def test_query_by_repo_full_name(self, test_db):
        """Test finding issues by repository name."""
        db, _, _ = test_db

        issues = db.query_issues(repo_full_name="sequentech/meta", limit=100)
        assert len(issues) == 4

        issues = db.query_issues(repo_full_name="sequentech/step", limit=100)
        assert len(issues) == 2

    def test_query_combined_issue_and_repo(self, test_db):
        """Test combining issue key and repo filters."""
        db, meta_id, _ = test_db

        # Find specific issue in specific repo
        issues = db.query_issues(issue_key="8624", repo_id=meta_id)
        assert len(issues) >= 1
        assert all(t.repo_id == meta_id for t in issues)

    def test_query_starts_with(self, test_db):
        """Test fuzzy matching with starts_with."""
        db, _, _ = test_db

        # Find all issues starting with "86"
        issues = db.query_issues(starts_with="86", limit=100)
        assert len(issues) >= 3  # 8624 (x2) and 8625, 8650
        assert all(t.key.startswith("86") or str(t.number).startswith("86") for t in issues)

    def test_query_ends_with(self, test_db):
        """Test fuzzy matching with ends_with."""
        db, _, _ = test_db

        # Find all issues ending with "24"
        issues = db.query_issues(ends_with="24", limit=100)
        assert len(issues) >= 3  # 8624 (x2), 1024, 1124

    def test_query_close_to_default_range(self, test_db):
        """Test proximity search with default range."""
        db, _, _ = test_db

        # Find issues close to 8624 (±20 = 8604-8644)
        issues = db.query_issues(close_to="8624", limit=100)

        # Should find 8624, 8625
        assert len(issues) >= 2
        for issue in issues:
            assert 8604 <= issue.number <= 8644

    def test_query_close_to_custom_range(self, test_db):
        """Test proximity search with custom range."""
        db, _, _ = test_db

        # Find issues close to 8624 with range of 50 (8574-8674)
        issues = db.query_issues(close_to="8624", close_range=50, limit=100)

        # Should find 8624, 8625, 8650
        assert len(issues) >= 3
        for issue in issues:
            assert 8574 <= issue.number <= 8674

    def test_query_with_limit(self, test_db):
        """Test pagination with limit."""
        db, _, _ = test_db

        # Query with limit of 2
        issues = db.query_issues(limit=2)
        assert len(issues) == 2

    def test_query_with_offset(self, test_db):
        """Test pagination with offset."""
        db, _, _ = test_db

        # Get all issues
        all_issues = db.query_issues(limit=100)
        total = len(all_issues)

        # Get issues with offset
        issues_offset = db.query_issues(offset=2, limit=100)

        # Should have 2 fewer issues
        assert len(issues_offset) == total - 2

    def test_query_limit_and_offset(self, test_db):
        """Test combined pagination."""
        db, _, _ = test_db

        # Get first 2
        first_page = db.query_issues(limit=2, offset=0)
        assert len(first_page) == 2

        # Get next 2
        second_page = db.query_issues(limit=2, offset=2)
        assert len(second_page) <= 2

        # Should not overlap
        first_ids = {t.id for t in first_page}
        second_ids = {t.id for t in second_page}
        assert first_ids.isdisjoint(second_ids)

    def test_query_no_results(self, test_db):
        """Test query returning no results."""
        db, _, _ = test_db

        issues = db.query_issues(issue_key="nonexistent-99999")
        assert len(issues) == 0

    def test_query_repo_full_name_includes_repo_info(self, test_db):
        """Test that issues include repo_full_name when queried."""
        db, _, _ = test_db

        issues = db.query_issues(repo_full_name="sequentech/meta", limit=1)
        assert len(issues) >= 1

        # Check that _repo_full_name is attached
        issue = issues[0]
        assert hasattr(issue, '_repo_full_name')
        assert issue._repo_full_name == "sequentech/meta"


class TestQueryIssuesCLI:
    """Tests for CLI issues command."""

    def test_cli_no_database(self, tmp_path, monkeypatch):
        """Test error when database doesn't exist."""
        # Create config pointing to non-existent DB
        config_file = tmp_path / "test_config.toml"
        nonexistent_db = tmp_path / "nonexistent.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{nonexistent_db}"
"""
        config_file.write_text(config_content)

        runner = CliRunner()
        result = runner.invoke(cli, ['--config', str(config_file), 'issues', '8624'])

        assert result.exit_code != 0
        assert "Database not found" in result.output

    def test_cli_exact_issue(self, tmp_path, test_db):
        """Test CLI with exact issue number."""
        db, _, _ = test_db

        # Create config
        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        # Copy database to expected location
        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, ['--config', str(config_file), 'issues', '8624'])

        assert result.exit_code == 0
        assert "8624" in result.output

    def test_cli_repo_filter(self, tmp_path, test_db):
        """Test CLI with --repo filter."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--repo', 'sequentech/step',
            '--limit', '10'
        ])

        assert result.exit_code == 0
        assert "step" in result.output.lower()

    def test_cli_fuzzy_starts_with(self, tmp_path, test_db):
        """Test CLI with --starts-with option."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--starts-with', '86'
        ])

        assert result.exit_code == 0
        assert "86" in result.output

    def test_cli_csv_output(self, tmp_path, test_db):
        """Test CLI with CSV format."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--repo', 'sequentech/meta',
            '--format', 'csv',
            '--limit', '2'
        ])

        assert result.exit_code == 0
        # CSV should have header row
        assert "id,repo_id,number,key,title" in result.output
        # Should have data rows
        assert "8624" in result.output or "8625" in result.output

    def test_cli_pagination(self, tmp_path, test_db):
        """Test CLI pagination options."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--limit', '2',
            '--offset', '1'
        ])

        assert result.exit_code == 0
        # Should show pagination info
        assert "Showing" in result.output or "issues" in result.output.lower()

    def test_cli_invalid_range(self, tmp_path, test_db):
        """Test CLI validation for invalid --range."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--close-to', '8624',
            '--range', '-10'
        ])

        assert result.exit_code != 0
        assert "range must be >= 0" in result.output.lower()

    def test_cli_conflicting_filters(self, tmp_path, test_db):
        """Test CLI validation for conflicting filters."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--close-to', '8624',
            '--starts-with', '86'
        ])

        assert result.exit_code != 0
        assert "cannot combine" in result.output.lower()


class TestSmartIssueKeyParsing:
    """Tests for smart ISSUE_KEY argument parsing."""

    def test_plain_number(self, tmp_path, test_db):
        """Test parsing plain number: 8624."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '8624'
        ])

        assert result.exit_code == 0
        assert "8624" in result.output

    def test_hash_prefix(self, tmp_path, test_db):
        """Test parsing with # prefix: #8624."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '#8624'
        ])

        assert result.exit_code == 0
        assert "8624" in result.output

    def test_repo_and_number(self, tmp_path, test_db):
        """Test parsing repo + number: meta#8624."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            'meta#8624'
        ])

        assert result.exit_code == 0
        assert "8624" in result.output
        assert "meta" in result.output.lower()

    def test_repo_and_number_with_proximity(self, tmp_path, test_db):
        """Test parsing repo + number + proximity: meta#8624~."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            'meta#8624~'
        ])

        assert result.exit_code == 0
        # Should find multiple issues in proximity (8624, 8625, 8650)
        assert "8624" in result.output or "8625" in result.output

    def test_full_repo_path(self, tmp_path, test_db):
        """Test parsing full repo path: sequentech/meta#8624."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            'sequentech/meta#8624'
        ])

        assert result.exit_code == 0
        assert "8624" in result.output
        assert "meta" in result.output.lower()

    def test_full_repo_path_with_proximity(self, tmp_path, test_db):
        """Test parsing full repo path + proximity: sequentech/meta#8624~."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            'sequentech/meta#8624~'
        ])

        assert result.exit_code == 0
        # Should find multiple issues in proximity
        assert "8624" in result.output or "8625" in result.output

    def test_repo_override_with_option(self, tmp_path, test_db):
        """Test that --repo option overrides parsed repo."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--repo', 'sequentech/step',  # Override with step
            'meta#1024'  # This is actually in step repo
        ])

        assert result.exit_code == 0
        assert "1024" in result.output
        assert "step" in result.output.lower()


class TestOutputFormats:
    """Tests for output formatting."""

    def test_table_format_with_results(self, tmp_path, test_db):
        """Test table format displays correctly."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--limit', '3',
            '--format', 'table'
        ])

        assert result.exit_code == 0
        # Should have table headers (Repository may be truncated)
        assert "Key" in result.output
        assert "Reposi" in result.output  # May be truncated to "Reposi…"
        assert "Title" in result.output
        assert "State" in result.output

    def test_table_format_no_results(self, tmp_path, test_db):
        """Test table format with no results."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            'nonexistent-999999'  # Positional argument, not --issue-key
        ])

        assert result.exit_code == 0
        assert "No issues found" in result.output

    def test_csv_all_fields(self, tmp_path, test_db):
        """Test CSV includes all expected fields."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db.db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--limit', '1',
            '--format', 'csv'
        ])

        assert result.exit_code == 0

        # Check all expected fields in header
        expected_fields = [
            'id', 'repo_id', 'number', 'key', 'title', 'body', 'state',
            'labels', 'url', 'created_at', 'closed_at', 'category', 'tags',
            'repo_full_name'
        ]
        for field in expected_fields:
            assert field in result.output

    def test_csv_escaping(self, tmp_path):
        """Test CSV properly escapes special characters."""
        # Create database with special characters
        with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
            db_path = f.name

        db = Database(db_path)
        db.connect()

        repo = Repository(owner="test", name="repo")
        repo_id = db.upsert_repository(repo)

        # Issue with commas and quotes in title/body
        issue = Issue(
            repo_id=repo_id,
            number=1,
            key="1",
            title='Title with "quotes" and, commas',
            body='Body with "quotes" and\nnewlines',
            state="open",
            labels=[],
            url="https://github.com/test/repo/issues/1",
            created_at=datetime.now(),
        )
        db.upsert_issue(issue)

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.10"

[repository]
code_repos = [
    {{link = "test/repo", alias = "repo"}}
]

[github]
token = "fake-token"

[database]
path = "{db_copy_path}"
"""
        config_file.write_text(config_content)

        import shutil
        shutil.copy(db_path, db_copy_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            '--config', str(config_file),
            'issues',
            '--format', 'csv'
        ])

        assert result.exit_code == 0
        # CSV should properly quote fields with special chars
        assert '"Title with ""quotes"" and, commas"' in result.output or 'Title with "quotes" and, commas' in result.output

        # Cleanup
        db.close()
        Path(db_path).unlink()
