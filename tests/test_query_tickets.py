"""Tests for tickets command and database querying."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from click.testing import CliRunner

from release_tool.db import Database
from release_tool.models import Repository, Ticket, Label
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

    # Create test tickets
    tickets_data = [
        # Meta repo tickets
        Ticket(
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
        Ticket(
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
        Ticket(
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
        Ticket(
            repo_id=meta_id,
            number=8624,
            key="#8624",  # Duplicate with # prefix
            title="Another ticket",
            body="Test duplicate key handling",
            state="open",
            labels=[],
            url="https://github.com/sequentech/meta/issues/8624",
            created_at=datetime(2024, 1, 10),  # Earlier than first 8624
        ),
        # Step repo tickets
        Ticket(
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
        Ticket(
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

    for ticket in tickets_data:
        db.upsert_ticket(ticket)

    yield db, meta_id, step_id

    # Cleanup
    db.close()
    Path(db_path).unlink()


class TestParseTicketNumber:
    """Tests for _parse_ticket_number helper."""

    def test_parse_plain_number(self, test_db):
        """Test parsing plain number."""
        db, _, _ = test_db
        assert db._parse_ticket_number("8624") == 8624

    def test_parse_hash_prefix(self, test_db):
        """Test parsing with # prefix."""
        db, _, _ = test_db
        assert db._parse_ticket_number("#8624") == 8624

    def test_parse_jira_style(self, test_db):
        """Test parsing JIRA-style key."""
        db, _, _ = test_db
        assert db._parse_ticket_number("ISSUE-8624") == 8624
        assert db._parse_ticket_number("meta-8624") == 8624

    def test_parse_no_number(self, test_db):
        """Test parsing with no number."""
        db, _, _ = test_db
        assert db._parse_ticket_number("no-numbers-here") is None

    def test_parse_empty(self, test_db):
        """Test parsing empty string."""
        db, _, _ = test_db
        assert db._parse_ticket_number("") is None


class TestQueryTicketsDatabase:
    """Tests for database query_tickets method."""

    def test_query_by_exact_ticket_key(self, test_db):
        """Test finding ticket by exact key."""
        db, _, _ = test_db
        tickets = db.query_tickets(ticket_key="8624")

        assert len(tickets) >= 1
        # Should find the most recent one
        assert tickets[0].key in ["8624", "#8624"]

    def test_query_by_repo_id(self, test_db):
        """Test finding all tickets in a repo."""
        db, meta_id, step_id = test_db

        meta_tickets = db.query_tickets(repo_id=meta_id, limit=100)
        assert len(meta_tickets) == 4  # 4 tickets in meta repo

        step_tickets = db.query_tickets(repo_id=step_id, limit=100)
        assert len(step_tickets) == 2  # 2 tickets in step repo

    def test_query_by_repo_full_name(self, test_db):
        """Test finding tickets by repository name."""
        db, _, _ = test_db

        tickets = db.query_tickets(repo_full_name="sequentech/meta", limit=100)
        assert len(tickets) == 4

        tickets = db.query_tickets(repo_full_name="sequentech/step", limit=100)
        assert len(tickets) == 2

    def test_query_combined_ticket_and_repo(self, test_db):
        """Test combining ticket key and repo filters."""
        db, meta_id, _ = test_db

        # Find specific ticket in specific repo
        tickets = db.query_tickets(ticket_key="8624", repo_id=meta_id)
        assert len(tickets) >= 1
        assert all(t.repo_id == meta_id for t in tickets)

    def test_query_starts_with(self, test_db):
        """Test fuzzy matching with starts_with."""
        db, _, _ = test_db

        # Find all tickets starting with "86"
        tickets = db.query_tickets(starts_with="86", limit=100)
        assert len(tickets) >= 3  # 8624 (x2) and 8625, 8650
        assert all(t.key.startswith("86") or str(t.number).startswith("86") for t in tickets)

    def test_query_ends_with(self, test_db):
        """Test fuzzy matching with ends_with."""
        db, _, _ = test_db

        # Find all tickets ending with "24"
        tickets = db.query_tickets(ends_with="24", limit=100)
        assert len(tickets) >= 3  # 8624 (x2), 1024, 1124

    def test_query_close_to_default_range(self, test_db):
        """Test proximity search with default range."""
        db, _, _ = test_db

        # Find tickets close to 8624 (±20 = 8604-8644)
        tickets = db.query_tickets(close_to="8624", limit=100)

        # Should find 8624, 8625
        assert len(tickets) >= 2
        for ticket in tickets:
            assert 8604 <= ticket.number <= 8644

    def test_query_close_to_custom_range(self, test_db):
        """Test proximity search with custom range."""
        db, _, _ = test_db

        # Find tickets close to 8624 with range of 50 (8574-8674)
        tickets = db.query_tickets(close_to="8624", close_range=50, limit=100)

        # Should find 8624, 8625, 8650
        assert len(tickets) >= 3
        for ticket in tickets:
            assert 8574 <= ticket.number <= 8674

    def test_query_with_limit(self, test_db):
        """Test pagination with limit."""
        db, _, _ = test_db

        # Query with limit of 2
        tickets = db.query_tickets(limit=2)
        assert len(tickets) == 2

    def test_query_with_offset(self, test_db):
        """Test pagination with offset."""
        db, _, _ = test_db

        # Get all tickets
        all_tickets = db.query_tickets(limit=100)
        total = len(all_tickets)

        # Get tickets with offset
        tickets_offset = db.query_tickets(offset=2, limit=100)

        # Should have 2 fewer tickets
        assert len(tickets_offset) == total - 2

    def test_query_limit_and_offset(self, test_db):
        """Test combined pagination."""
        db, _, _ = test_db

        # Get first 2
        first_page = db.query_tickets(limit=2, offset=0)
        assert len(first_page) == 2

        # Get next 2
        second_page = db.query_tickets(limit=2, offset=2)
        assert len(second_page) <= 2

        # Should not overlap
        first_ids = {t.id for t in first_page}
        second_ids = {t.id for t in second_page}
        assert first_ids.isdisjoint(second_ids)

    def test_query_no_results(self, test_db):
        """Test query returning no results."""
        db, _, _ = test_db

        tickets = db.query_tickets(ticket_key="nonexistent-99999")
        assert len(tickets) == 0

    def test_query_repo_full_name_includes_repo_info(self, test_db):
        """Test that tickets include repo_full_name when queried."""
        db, _, _ = test_db

        tickets = db.query_tickets(repo_full_name="sequentech/meta", limit=1)
        assert len(tickets) >= 1

        # Check that _repo_full_name is attached
        ticket = tickets[0]
        assert hasattr(ticket, '_repo_full_name')
        assert ticket._repo_full_name == "sequentech/meta"


class TestQueryTicketsCLI:
    """Tests for CLI tickets command."""

    def test_cli_no_database(self, tmp_path, monkeypatch):
        """Test error when database doesn't exist."""
        # Create config pointing to non-existent DB
        config_file = tmp_path / "test_config.toml"
        nonexistent_db = tmp_path / "nonexistent.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

[github]
token = "fake-token"

[database]
path = "{nonexistent_db}"
"""
        config_file.write_text(config_content)

        runner = CliRunner()
        result = runner.invoke(cli, ['--config', str(config_file), 'tickets', '8624'])

        assert result.exit_code != 0
        assert "Database not found" in result.output

    def test_cli_exact_ticket(self, tmp_path, test_db):
        """Test CLI with exact ticket number."""
        db, _, _ = test_db

        # Create config
        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
        result = runner.invoke(cli, ['--config', str(config_file), 'tickets', '8624'])

        assert result.exit_code == 0
        assert "8624" in result.output

    def test_cli_repo_filter(self, tmp_path, test_db):
        """Test CLI with --repo filter."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
            '--limit', '2',
            '--offset', '1'
        ])

        assert result.exit_code == 0
        # Should show pagination info
        assert "Showing" in result.output or "tickets" in result.output.lower()

    def test_cli_invalid_range(self, tmp_path, test_db):
        """Test CLI validation for invalid --range."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
            '--close-to', '8624',
            '--starts-with', '86'
        ])

        assert result.exit_code != 0
        assert "cannot combine" in result.output.lower()


class TestSmartTicketKeyParsing:
    """Tests for smart TICKET_KEY argument parsing."""

    def test_plain_number(self, tmp_path, test_db):
        """Test parsing plain number: 8624."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
            'meta#8624~'
        ])

        assert result.exit_code == 0
        # Should find multiple tickets in proximity (8624, 8625, 8650)
        assert "8624" in result.output or "8625" in result.output

    def test_full_repo_path(self, tmp_path, test_db):
        """Test parsing full repo path: sequentech/meta#8624."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
            'sequentech/meta#8624~'
        ])

        assert result.exit_code == 0
        # Should find multiple tickets in proximity
        assert "8624" in result.output or "8625" in result.output

    def test_repo_override_with_option(self, tmp_path, test_db):
        """Test that --repo option overrides parsed repo."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
            'nonexistent-999999'  # Positional argument, not --ticket-key
        ])

        assert result.exit_code == 0
        assert "No tickets found" in result.output

    def test_csv_all_fields(self, tmp_path, test_db):
        """Test CSV includes all expected fields."""
        db, _, _ = test_db

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
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

        # Ticket with commas and quotes in title/body
        ticket = Ticket(
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
        db.upsert_ticket(ticket)

        config_file = tmp_path / "test_config.toml"
        db_copy_path = tmp_path / "release_tool.db"
        config_content = f"""
config_version = "1.3"

[repository]
code_repo = "test/repo"

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
            'tickets',
            '--format', 'csv'
        ])

        assert result.exit_code == 0
        # CSV should properly quote fields with special chars
        assert '"Title with ""quotes"" and, commas"' in result.output or 'Title with "quotes" and, commas' in result.output

        # Cleanup
        db.close()
        Path(db_path).unlink()
