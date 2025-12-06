# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for category validation and "Other" category fallback."""

import pytest
from io import StringIO
from release_tool.policies import ReleaseNoteGenerator
from release_tool.config import Config
from release_tool.models import ReleaseNote, Author


@pytest.fixture
def config_with_other_category():
    """Config with 'Other' category matching hardcoded fallback."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Bug Fixes", "labels": ["bug"], "order": 2},
                {"name": "Other", "labels": [], "order": 99},
            ],
        }
    })


@pytest.fixture
def config_with_mismatched_other():
    """Config with 'Other Changes' instead of 'Other' (mismatch)."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Bug Fixes", "labels": ["bug"], "order": 2},
                {"name": "Other Changes", "labels": [], "order": 99},
            ],
        }
    })


@pytest.fixture
def config_with_release_output_template():
    """Config with custom release_output_template."""
    return Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Other", "labels": [], "order": 99},
            ],
            "release_output_template": """# {{ title }}
{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}
{% endfor %}"""
        }
    })


def test_other_category_matches_hardcoded_fallback(config_with_other_category):
    """Test that category with alias='other' works as fallback for unmatched labels."""
    generator = ReleaseNoteGenerator(config_with_other_category)

    # Verify the fallback category is detected by alias
    assert generator._get_fallback_category_name() == "Other"

    # Create a note with no matching labels (will be categorized as "Other")
    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Uncategorized change",
            category="Other",  # Detected via alias='other'
            labels=["random-label"],  # No matching category label
            authors=[author],
            pr_numbers=[123]
        )
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Should include the note under "Other" category
    assert "Other" in output
    assert "Uncategorized change" in output


def test_missing_notes_warning_on_category_mismatch(config_with_mismatched_other, capsys):
    """Test that warning is issued when notes have category not in config."""
    generator = ReleaseNoteGenerator(config_with_mismatched_other)

    # Create a note categorized as "Other" but config has "Other Changes"
    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Uncategorized change",
            category="Other",  # This won't match "Other Changes" in config
            labels=[],
            authors=[author],
            pr_numbers=[123]
        )
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Capture output
    captured = capsys.readouterr()

    # Should issue a warning about missing notes
    assert "Warning" in captured.out or "⚠" in captured.out
    assert "not rendered" in captured.out or "Other" in captured.out


def test_all_notes_rendered_in_template(config_with_other_category):
    """Test that every note in grouped_notes appears in final output."""
    generator = ReleaseNoteGenerator(config_with_other_category)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Feature 1",
            category="Features",
            labels=["feature"],
            authors=[author],
            pr_numbers=[1]
        ),
        ReleaseNote(
            title="Bug fix 1",
            category="Bug Fixes",
            labels=["bug"],
            authors=[author],
            pr_numbers=[2]
        ),
        ReleaseNote(
            title="Other change",
            category="Other",
            labels=[],
            authors=[author],
            pr_numbers=[3]
        ),
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # All notes should appear in output
    assert "Feature 1" in output
    assert "Bug fix 1" in output
    assert "Other change" in output


def test_orphaned_category_detection(config_with_other_category, capsys):
    """Test that categories in grouped_notes but not in config are detected."""
    generator = ReleaseNoteGenerator(config_with_other_category)

    # Manually create grouped_notes with an extra category
    author = Author(name="Test", username="test")
    note1 = ReleaseNote(
        title="Feature",
        category="Features",
        labels=["feature"],
        authors=[author]
    )
    note2 = ReleaseNote(
        title="Unknown",
        category="Unknown Category",  # Not in config!
        labels=[],
        authors=[author]
    )

    grouped = {
        "Features": [note1],
        "Unknown Category": [note2],
    }

    output = generator.format_markdown(grouped, "1.0.0")

    captured = capsys.readouterr()

    # Should warn about orphaned category
    assert "Warning" in captured.out or "⚠" in captured.out
    assert "Unknown Category" in captured.out


def test_validation_with_release_output_template(config_with_release_output_template):
    """Test validation works with custom release_output_template."""
    generator = ReleaseNoteGenerator(config_with_release_output_template)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Feature",
            category="Features",
            labels=["feature"],
            authors=[author]
        ),
        ReleaseNote(
            title="Other",
            category="Other",
            labels=[],
            authors=[author]
        ),
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Both notes should be rendered with custom template
    assert "Feature" in output
    assert "Other" in output


def test_validation_with_legacy_layout():
    """Test validation works with legacy layout (no release_output_template)."""
    # Config without release_output_template uses legacy layout
    config = Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "release_notes": {
            "categories": [
                {"name": "🚀 Features", "labels": ["feature"], "order": 1},
                {"name": "Other", "labels": [], "order": 99},
            ],
        }
    })

    generator = ReleaseNoteGenerator(config)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Feature",
            category="🚀 Features",
            labels=["feature"],
            authors=[author]
        ),
        ReleaseNote(
            title="Other change",
            category="Other",
            labels=[],
            authors=[author]
        ),
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Both should be rendered in legacy layout
    assert "Feature" in output
    assert "Other change" in output


def test_no_warning_when_all_notes_rendered(config_with_other_category, capsys):
    """Test that no warning is issued when all notes are properly rendered."""
    generator = ReleaseNoteGenerator(config_with_other_category)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Feature",
            category="Features",
            labels=["feature"],
            authors=[author]
        ),
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    captured = capsys.readouterr()

    # Should NOT warn when everything is fine
    assert "not rendered" not in captured.out


def test_validation_counts_notes_correctly(config_with_other_category):
    """Test that validation correctly counts notes across multiple categories."""
    generator = ReleaseNoteGenerator(config_with_other_category)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(title=f"Feature {i}", category="Features", labels=["feature"], authors=[author])
        for i in range(3)
    ] + [
        ReleaseNote(title=f"Bug {i}", category="Bug Fixes", labels=["bug"], authors=[author])
        for i in range(2)
    ] + [
        ReleaseNote(title="Other", category="Other", labels=[], authors=[author])
    ]

    grouped = generator.group_by_category(notes)

    # Total should be 6 notes
    total_in_grouped = sum(len(notes_list) for notes_list in grouped.values())
    assert total_in_grouped == 6

    output = generator.format_markdown(grouped, "1.0.0")

    # All 6 should appear
    for i in range(3):
        assert f"Feature {i}" in output
    for i in range(2):
        assert f"Bug {i}" in output
    assert "Other" in output


def test_empty_category_does_not_affect_validation(config_with_other_category):
    """Test that empty categories don't trigger validation warnings."""
    generator = ReleaseNoteGenerator(config_with_other_category)

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Feature",
            category="Features",
            labels=["feature"],
            authors=[author]
        ),
        # No "Bug Fixes" or "Other" notes - those categories will be empty
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Should work fine with empty categories
    assert "Feature" in output


def test_custom_fallback_category_name():
    """Test that fallback category can have a custom name as long as alias='other'."""
    # Config with custom "Miscellaneous" name but alias="other"
    config = Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "github": {"token": "test_token"},
        "release_notes": {
            "categories": [
                {"name": "Features", "labels": ["feature"], "order": 1},
                {"name": "Miscellaneous", "labels": [], "order": 99, "alias": "other"},
            ],
        }
    })

    generator = ReleaseNoteGenerator(config)

    # Should detect "Miscellaneous" as the fallback category
    assert generator._get_fallback_category_name() == "Miscellaneous"

    author = Author(name="Test", username="test")
    notes = [
        ReleaseNote(
            title="Uncategorized",
            category="Miscellaneous",  # Custom name with alias='other'
            labels=[],
            authors=[author]
        ),
    ]

    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Should appear under "Miscellaneous" category
    assert "Miscellaneous" in output
    assert "Uncategorized" in output
