"""Tests for release_output_template master template functionality."""

import pytest
from datetime import datetime
from release_tool.policies import ReleaseNoteGenerator
from release_tool.config import Config
from release_tool.models import ReleaseNote, Author


@pytest.fixture
def test_config_with_release_output_template():
    """Create a test configuration with release_output_template."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Bug Fixes", "labels": ["bug"], "order": 2},
                {"name": "Documentation", "labels": ["docs"], "order": 3},
            ],
            "release_output_template": """# {{ title }}

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}"""
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_config_flat_list():
    """Config with flat list output template."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Bug Fixes", "labels": ["bug"], "order": 2},
                {"name": "Documentation", "labels": ["docs"], "order": 3},
            ],
            "release_output_template": """# {{ title }}

{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}"""
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def test_config_with_migrations():
    """Config with migrations section."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Bug Fixes", "labels": ["bug"], "order": 2},
            ],
            "release_output_template": """# {{ title }}

## Changes
{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}

## Migration Notes
{% for note in all_notes %}
{% if note.migration_notes %}
### {{ note.title }}
{{ note.migration_notes }}
{% endif %}
{% endfor %}"""
        }
    }
    return Config.from_dict(config_dict)


@pytest.fixture
def sample_notes():
    """Create sample release notes."""
    author1 = Author(name="Alice", username="alice")
    author2 = Author(name="Bob", username="bob")

    return [
        ReleaseNote(
            title="Add new feature",
            category="Features",
            labels=["feature"],
            authors=[author1],
            pr_numbers=[123],
            url="https://github.com/test/repo/pull/123"
        ),
        ReleaseNote(
            title="Fix critical bug",
            category="Bug Fixes",
            labels=["bug"],
            authors=[author2],
            pr_numbers=[124],
            url="https://github.com/test/repo/pull/124",
            migration_notes="Update config to use new format"
        ),
        ReleaseNote(
            title="Update docs",
            category="Documentation",
            labels=["docs"],
            authors=[author1, author2],
            pr_numbers=[125]
        )
    ]


def test_release_output_template_with_categories(test_config_with_release_output_template, sample_notes):
    """Test release_output_template with category iteration."""
    generator = ReleaseNoteGenerator(test_config_with_release_output_template)
    grouped = generator.group_by_category(sample_notes)

    output = generator.format_markdown(grouped, "1.0.0")

    assert "# Release 1.0.0" in output
    assert "## Features" in output
    assert "## Bug Fixes" in output
    assert "## Documentation" in output
    assert "Add new feature" in output
    assert "Fix critical bug" in output
    assert "Update docs" in output


def test_release_output_template_flat_list(test_config_flat_list, sample_notes):
    """Test release_output_template with flat list (no categories)."""
    generator = ReleaseNoteGenerator(test_config_flat_list)
    grouped = generator.group_by_category(sample_notes)

    output = generator.format_markdown(grouped, "1.0.0")

    assert "# Release 1.0.0" in output
    # Should NOT have category headers
    assert "## Features" not in output
    assert "## Bug Fixes" not in output
    # But should have all notes
    assert "Add new feature" in output
    assert "Fix critical bug" in output
    assert "Update docs" in output


def test_release_output_template_with_migrations(test_config_with_migrations, sample_notes):
    """Test release_output_template with separate migrations section."""
    generator = ReleaseNoteGenerator(test_config_with_migrations)
    grouped = generator.group_by_category(sample_notes)

    output = generator.format_markdown(grouped, "2.0.0")

    assert "# Release 2.0.0" in output
    assert "## Changes" in output
    assert "## Migration Notes" in output
    # Migration note should appear in dedicated section
    assert "### Fix critical bug" in output
    assert "Update config to use new format" in output
    # Note without migration should not appear in migration section
    assert "### Add new feature" not in output


def test_legacy_format_without_release_output_template():
    """Test that legacy format still works when release_output_template is not set."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Test change",
            category="🚀 Features",
            labels=["feature"],
            authors=[author]
        )
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Now uses default release_output_template
    # Note: Title header removed - appears in GitHub release UI instead
    assert "🚀 Features" in output
    assert "Test change" in output


def test_render_entry_includes_all_fields():
    """Test that render_entry correctly passes all fields to entry template."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
            ],
            "entry_template": """- {{ title }} by {{ authors[0].mention }}
{% if migration_notes %}Migration: {{ migration_notes }}{% endif %}""",
            "release_output_template": """# {{ title }}
{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}"""
        }
    }
    config = Config.from_dict(config_dict)

    author = Author(name="Alice", username="alice")
    notes = [
        ReleaseNote(
            title="Add feature",
            category="Features",
            labels=["feature"],
            authors=[author],
            migration_notes="Run migration script"
        )
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    assert "Add feature by @alice" in output
    assert "Migration: Run migration script" in output


def test_html_whitespace_processing_in_release_output_template():
    """Test that HTML-like whitespace processing works in release_output_template."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "release_output_template": """# {{ title }}

Test with    multiple   spaces
and<br>line break"""
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)
    output = generator.format_markdown({}, "1.0.0")

    # Multiple spaces should collapse to single space
    assert "Test with multiple spaces" in output
    # <br> should create an empty line
    lines = output.split('\n')
    assert "and" in output
    assert "line break" in output


def test_nbsp_entity_preservation():
    """Test that &nbsp; entities are preserved as spaces and not collapsed."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "release_output_template": """# {{ title }}

Test&nbsp;&nbsp;two&nbsp;spaces
Normal    spaces   collapse
Mixed:&nbsp;&nbsp;preserved    and   collapsed"""
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)
    output = generator.format_markdown({}, "1.0.0")

    # Two consecutive &nbsp; should preserve two spaces
    assert "Test  two spaces" in output

    # Normal multiple spaces should collapse
    assert "Normal spaces collapse" in output

    # Mixed usage: &nbsp; preserved, normal spaces collapsed
    assert "Mixed:  preserved and collapsed" in output


def test_nbsp_in_entry_template():
    """Test that &nbsp; works correctly in entry_template."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
            ],
            "entry_template": """- {{ title }}<br>&nbsp;&nbsp;by {{ authors[0].mention }}""",
            "release_output_template": """# {{ title }}
{% for note in all_notes %}
{{ render_entry(note) }}
{% endfor %}"""
        }
    }
    config = Config.from_dict(config_dict)

    author = Author(name="Alice", username="alice")
    notes = [
        ReleaseNote(
            title="Add feature",
            category="Features",
            labels=["feature"],
            authors=[author]
        )
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Should have two spaces (from &nbsp;&nbsp;) before "by"
    assert "  by @alice" in output
