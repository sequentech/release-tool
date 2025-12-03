<!--
SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>

SPDX-License-Identifier: MIT
-->

# Release Tool - Testing Patterns and Expectations

## Testing Philosophy

All modules must have comprehensive unit tests. Tests should:
- Cover both success and error paths
- Use fixtures for common setup
- Mock external dependencies (GitHub API, Git operations)
- Run fast (mock network calls)
- Be maintainable (clear naming, good assertions)

## Test Structure

### File Organization
```
tests/
├── test_models.py        # Pydantic model tests
├── test_config.py        # Configuration loading and validation
├── test_db.py            # Database operations
├── test_git_ops.py       # Git repository operations
├── test_github_utils.py  # GitHub API client (if needed)
├── test_policies.py      # Ticket extraction, consolidation, generation
├── test_sync.py          # Sync manager tests
├── test_output_template.py  # Template rendering
└── test_default_template.py # Default template behavior
```

### Current Coverage
- **Total tests**: 74
- **Modules covered**: 8/10
- **Target coverage**: >80% for critical paths

## Common Test Patterns

### 1. Pydantic Model Tests

**Pattern**: Test parsing, validation, and methods
```python
def test_semantic_version_parse():
    """Test parsing various version formats."""
    v = SemanticVersion.parse("2.0.0")
    assert v.major == 2
    assert v.minor == 0
    assert v.patch == 0
    assert v.is_final() is True

def test_semantic_version_prerelease():
    """Test prerelease version parsing."""
    v = SemanticVersion.parse("2.0.0-rc.1")
    assert v.prerelease == "rc.1"
    assert v.is_final() is False

def test_invalid_version_raises():
    """Test that invalid versions raise ValueError."""
    with pytest.raises(ValueError):
        SemanticVersion.parse("invalid")
```

### 2. Configuration Tests

**Pattern**: Test loading, validation, defaults
```python
def test_config_from_dict():
    """Test creating config from dictionary."""
    config_dict = {
        "repository": {"code_repo": "owner/repo"},
        "sync": {"parallel_workers": 20}
    }
    config = Config.from_dict(config_dict)

    assert config.repository.code_repo == "owner/repo"
    assert config.sync.parallel_workers == 20

def test_config_defaults():
    """Test that defaults are applied correctly."""
    config = Config.from_dict({"repository": {"code_repo": "test/repo"}})

    assert config.sync.parallel_workers == 20  # Default
    assert config.sync.show_progress is True
```

### 3. Database Tests

**Pattern**: Use in-memory SQLite, test CRUD operations
```python
@pytest.fixture
def test_db():
    """Create in-memory test database."""
    db = Database(":memory:")
    db.connect()
    db.init_db()
    yield db
    db.close()

def test_upsert_ticket(test_db):
    """Test inserting and updating tickets."""
    ticket = Ticket(
        repo_id=1,
        number=123,
        key="#123",
        title="Test ticket",
        body="Description",
        state="open",
        labels=[],
        url="https://github.com/owner/repo/issues/123"
    )

    # Insert
    test_db.upsert_ticket(ticket)

    # Verify
    result = test_db.get_ticket_by_number(1, 123)
    assert result.title == "Test ticket"

    # Update
    ticket.title = "Updated title"
    test_db.upsert_ticket(ticket)

    # Verify update
    result = test_db.get_ticket_by_number(1, 123)
    assert result.title == "Updated title"
```

### 4. Git Operations Tests

**Pattern**: Mock Git repository, test commit extraction
```python
@pytest.fixture
def mock_git_repo(tmp_path):
    """Create a mock Git repository for testing."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize repo with test data
    # ... create commits, tags, etc.

    return repo_path

def test_find_comparison_version():
    """Test automatic version comparison detection."""
    versions = [
        SemanticVersion.parse("1.0.0"),
        SemanticVersion.parse("1.1.0"),
        SemanticVersion.parse("2.0.0-rc.1"),
        SemanticVersion.parse("2.0.0")
    ]

    # Final version should compare to previous final
    comparison = find_comparison_version(
        SemanticVersion.parse("2.0.0"),
        versions
    )
    assert comparison.to_string() == "1.1.0"

    # RC should compare to previous RC or final
    comparison = find_comparison_version(
        SemanticVersion.parse("2.0.0-rc.1"),
        versions
    )
    assert comparison.to_string() == "1.1.0"
```

### 5. GitHub API Tests

**Pattern**: Mock GitHub client, test parallelization
```python
@pytest.fixture
def mock_github():
    """Create mock GitHub client."""
    mock = Mock(spec=GitHubClient)
    return mock

def test_search_ticket_numbers(mock_github):
    """Test ticket number search."""
    # Mock the search results
    mock_github.search_ticket_numbers.return_value = [1, 2, 3, 4, 5]

    numbers = mock_github.search_ticket_numbers("owner/repo", since=None)

    assert len(numbers) == 5
    assert 1 in numbers
    mock_github.search_ticket_numbers.assert_called_once()
```

### 6. Sync Manager Tests

**Pattern**: Test incremental sync, filtering, parallel fetch
```python
def test_incremental_sync_filters_existing(test_db, mock_github):
    """Test that incremental sync only fetches new items."""
    # Setup: Add existing tickets to DB
    for num in [1, 2, 3]:
        ticket = Ticket(
            repo_id=1, number=num, key=f"#{num}",
            title=f"Ticket {num}", body="", state="open",
            labels=[], url=f"https://github.com/owner/repo/issues/{num}"
        )
        test_db.upsert_ticket(ticket)

    # Mock GitHub to return all tickets (including existing)
    mock_github.search_ticket_numbers.return_value = [1, 2, 3, 4, 5, 6]

    sync_manager = SyncManager(test_config, test_db, mock_github)

    # Get ticket numbers to fetch
    to_fetch = sync_manager._get_ticket_numbers_to_fetch("owner/repo", None)

    # Should only fetch new tickets (4, 5, 6)
    assert set(to_fetch) == {4, 5, 6}
```

### 7. Policy Tests

**Pattern**: Test ticket extraction, consolidation, categorization
```python
class TestTicketExtractor:
    """Test ticket reference extraction."""

    def test_extract_from_branch_name(self):
        """Test extracting ticket from branch name."""
        commit = Commit(
            sha="abc123",
            message="Fix bug",
            author_name="Test",
            author_email="test@example.com",
            timestamp=datetime.now(),
            branch_name="feat/meta-123/description"
        )

        extractor = TicketExtractor(test_config)
        ticket_key = extractor.extract_from_commit(commit)

        assert ticket_key == "meta-123"

    def test_extract_from_pr_body(self):
        """Test extracting parent issue from PR body."""
        pr = PullRequest(
            repo_id=1, number=456,
            title="Fix bug",
            body="Parent issue: https://github.com/owner/repo/issues/123",
            # ... other fields
        )

        extractor = TicketExtractor(test_config)
        ticket_key = extractor.extract_from_pr(pr)

        assert ticket_key == "#123"
```

### 8. Template Rendering Tests

**Pattern**: Test Jinja2 template output
```python
def test_output_template_with_categories():
    """Test template renders categories correctly."""
    notes = [
        ReleaseNote(
            title="Add feature",
            category="🚀 Features",
            pr_numbers=[1],
            # ... other fields
        ),
        ReleaseNote(
            title="Fix bug",
            category="🛠 Bug Fixes",
            pr_numbers=[2],
            # ... other fields
        )
    ]

    generator = ReleaseNoteGenerator(test_config)
    output = generator.render_template("2.0.0", notes)

    assert "🚀 Features" in output
    assert "Add feature" in output
    assert "🛠 Bug Fixes" in output
    assert "Fix bug" in output
```

## Test Fixtures

### Common Fixtures
```python
@pytest.fixture
def test_config():
    """Create test configuration."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "sync": {"parallel_workers": 20}
    })

@pytest.fixture
def test_db():
    """In-memory test database."""
    db = Database(":memory:")
    db.connect()
    db.init_db()
    yield db
    db.close()

@pytest.fixture
def mock_github():
    """Mock GitHub client."""
    return Mock(spec=GitHubClient)
```

## Running Tests

### Basic Test Commands
```bash
# Run all tests
pytest

# Run specific module
pytest tests/test_sync.py -v

# Run with coverage
pytest --cov=release_tool --cov-report=term-missing

# Run specific test
pytest tests/test_models.py::TestSemanticVersion::test_parse_simple_version -v

# Run with verbose output
pytest -vv

# Run with print statements visible
pytest -s
```

### Test Naming Conventions
- Test files: `test_<module>.py`
- Test classes: `Test<Feature>` (e.g., `TestTicketExtractor`)
- Test functions: `test_<what_it_tests>` (e.g., `test_extract_from_branch_name`)

## Assertions

### Good Assertions (Specific and Clear)
```python
assert result.title == "Expected Title"
assert len(results) == 5
assert "feature" in result.labels
assert result.is_final() is True
with pytest.raises(ValueError, match="Invalid version"):
    SemanticVersion.parse("invalid")
```

### Bad Assertions (Vague)
```python
assert result  # What are we checking?
assert True    # Meaningless
```

## Mocking Best Practices

### Mock External Dependencies
```python
# Mock GitHub API
mock_gh = Mock(spec=GitHubClient)
mock_gh.search_ticket_numbers.return_value = [1, 2, 3]

# Mock file system
with patch('pathlib.Path.exists', return_value=True):
    # Test code

# Mock time
with patch('datetime.datetime.now', return_value=fixed_time):
    # Test code
```

### Don't Mock What You Own
```python
# DON'T mock your own models
mock_ticket = Mock(spec=Ticket)  # Bad

# DO create real instances
ticket = Ticket(...)  # Good
```

## Test Coverage Goals

- **Critical paths**: 100% (sync, generate, version comparison)
- **Business logic**: >90% (policies, consolidation)
- **Utilities**: >80% (config, db, models)
- **CLI**: >70% (main.py - integration tests)

## When Tests Fail

1. **Read the error message carefully**
2. **Check if test expectations match new behavior**
3. **Update tests when refactoring** (don't just delete failing tests)
4. **Add tests for new features**
5. **Run affected tests before committing**
