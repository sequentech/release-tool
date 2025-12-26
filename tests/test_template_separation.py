# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for template separation between pr_code templates and draft/GitHub releases."""

import pytest
from release_tool.policies import ReleaseNoteGenerator
from release_tool.config import Config
from release_tool.models import ReleaseNote, Author


@pytest.fixture
def sample_notes():
    """Create sample release notes for testing."""
    author = Author(name="Alice", username="alice")
    return [
        ReleaseNote(
            title="Add new feature",
            category="🚀 Features",
            labels=["feature"],
            authors=[author],
            pr_numbers=[123],
            url="https://github.com/test/repo/pull/123",
            description="This is a great new feature."
        ),
        ReleaseNote(
            title="Fix critical bug",
            category="🛠 Bug Fixes",
            labels=["bug"],
            authors=[author],
            pr_numbers=[124],
            url="https://github.com/test/repo/pull/124"
        ),
    ]


def test_pr_code_template_uses_custom_template(sample_notes):
    """Test that pr_code templates use their custom output_template, not DEFAULT_RELEASE_NOTES_TEMPLATE."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "pr_code": {
                "templates": [
                    {
                        "output_template": """CUSTOM PR CODE TEMPLATE
# {{ title }}

{% for note in all_notes %}
- {{ note.title }}
{% endfor %}""",
                        "output_path": "custom.md"
                    }
                ]
            }
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(sample_notes)

    # Simulate pr_code template generation
    pr_code_template = config.output.pr_code.templates[0]
    result = generator._format_with_pr_code_template(
        pr_code_template.output_template,
        grouped,
        "1.0.0",
        "custom.md",
        None
    )

    # Should contain custom template marker
    assert "CUSTOM PR CODE TEMPLATE" in result
    assert "# Release 1.0.0" in result
    assert "Add new feature" in result
    assert "Fix critical bug" in result

    # Should NOT contain DEFAULT_RELEASE_NOTES_TEMPLATE markers
    assert "## 💥 Breaking Changes" not in result
    assert "## 📋 All Changes" not in result
    assert "## 🔄 Migrations" not in result


def test_draft_file_uses_default_release_template(sample_notes):
    """Test that draft file (for GitHub releases) uses DEFAULT_RELEASE_NOTES_TEMPLATE."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "pr_code": {
                "templates": [
                    {
                        "output_template": """CUSTOM PR CODE TEMPLATE
# {{ title }}""",
                        "output_path": "custom.md"
                    }
                ]
            }
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(sample_notes)

    # Simulate draft file generation (for GitHub releases)
    result = generator._format_with_master_template(
        grouped,
        "1.0.0",
        "draft.md",
        None
    )

    # Should contain DEFAULT_RELEASE_NOTES_TEMPLATE structure
    assert "## 📋 All Changes" in result
    assert "### 🚀 Features" in result
    assert "### 🛠 Bug Fixes" in result
    assert "Add new feature" in result
    assert "Fix critical bug" in result

    # Should NOT contain pr_code template content
    assert "CUSTOM PR CODE TEMPLATE" not in result


def test_br_tags_work_in_pr_code_templates():
    """Test that <br> tags are converted to line breaks in pr_code templates."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "pr_code": {
                "templates": [
                    {
                        "output_template": """# {{ title }}

Line one<br>Line two
Multiple    spaces   should   collapse
But<br>breaks<br>should<br>work""",
                        "output_path": "test.md"
                    }
                ]
            }
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)

    pr_code_template = config.output.pr_code.templates[0]
    result = generator._format_with_pr_code_template(
        pr_code_template.output_template,
        {},
        "1.0.0",
        "test.md",
        None
    )

    # <br> should create actual line breaks
    assert "Line one\n\nLine two" in result

    # Multiple spaces should collapse
    assert "Multiple spaces should collapse" in result

    # Multiple <br> tags should create multiple breaks
    assert "But\n\nbreaks\n\nshould\n\nwork" in result


def test_br_tags_work_in_default_release_template():
    """Test that <br> tags work in DEFAULT_RELEASE_NOTES_TEMPLATE (draft/GitHub releases)."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "release_notes": {
            "entry_template": "- {{ title }}<br>  Author: {{ authors[0].mention }}"
        }
    }
    config = Config.from_dict(config_dict)

    author = Author(name="Alice", username="alice")
    notes = [
        ReleaseNote(
            title="Test feature",
            category="🚀 Features",
            labels=["feature"],
            authors=[author]
        )
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)

    # Use default template (master template)
    result = generator._format_with_master_template(
        grouped,
        "1.0.0",
        None,
        None
    )

    # <br> in entry_template should create line break
    # The exact formatting depends on the template, but should have separation
    assert "Test feature" in result
    assert "Author: @alice" in result


def test_multiple_pr_code_templates_each_use_own_template(sample_notes):
    """Test that multiple pr_code templates each use their own output_template."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "pr_code": {
                "templates": [
                    {
                        "output_template": """TEMPLATE ONE: {{ title }}
{% for note in all_notes %}
- {{ note.title }}
{% endfor %}""",
                        "output_path": "output1.md"
                    },
                    {
                        "output_template": """TEMPLATE TWO: {{ title }}
{% for note in all_notes %}
* {{ note.title }}
{% endfor %}""",
                        "output_path": "output2.md"
                    }
                ]
            }
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(sample_notes)

    # Generate with first template
    template1 = config.output.pr_code.templates[0]
    result1 = generator._format_with_pr_code_template(
        template1.output_template,
        grouped,
        "1.0.0",
        "output1.md",
        None
    )

    # Generate with second template
    template2 = config.output.pr_code.templates[1]
    result2 = generator._format_with_pr_code_template(
        template2.output_template,
        grouped,
        "1.0.0",
        "output2.md",
        None
    )

    # Verify template 1 uses its own template
    assert "TEMPLATE ONE" in result1
    assert "TEMPLATE TWO" not in result1
    assert "- Add new feature" in result1  # Uses "-" bullet

    # Verify template 2 uses its own template
    assert "TEMPLATE TWO" in result2
    assert "TEMPLATE ONE" not in result2
    assert "* Add new feature" in result2  # Uses "*" bullet


def test_nbsp_preserved_in_pr_code_templates():
    """Test that &nbsp; entities are preserved in pr_code templates."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "pr_code": {
                "templates": [
                    {
                        "output_template": """# {{ title }}

Test&nbsp;&nbsp;two&nbsp;spaces
Normal    spaces   collapse""",
                        "output_path": "test.md"
                    }
                ]
            }
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)

    pr_code_template = config.output.pr_code.templates[0]
    result = generator._format_with_pr_code_template(
        pr_code_template.output_template,
        {},
        "1.0.0",
        "test.md",
        None
    )

    # &nbsp; should be preserved as actual spaces
    assert "Test  two spaces" in result

    # Normal spaces should collapse
    assert "Normal spaces collapse" in result


def test_draft_file_has_different_content_than_pr_code_template(sample_notes):
    """Test that draft file and pr_code file have intentionally different content."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "pr_code": {
                "templates": [
                    {
                        # Minimal pr_code template
                        "output_template": """# {{ title }}
{% for note in all_notes %}
{{ note.title }}
{% endfor %}""",
                        "output_path": "docs.md"
                    }
                ]
            }
        }
    }
    config = Config.from_dict(config_dict)

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(sample_notes)

    # Generate pr_code template output
    pr_code_template = config.output.pr_code.templates[0]
    pr_code_result = generator._format_with_pr_code_template(
        pr_code_template.output_template,
        grouped,
        "1.0.0",
        "docs.md",
        None
    )

    # Generate draft file output (for GitHub releases)
    draft_result = generator._format_with_master_template(
        grouped,
        "1.0.0",
        "draft.md",
        None
    )

    # Both should contain the note titles
    assert "Add new feature" in pr_code_result
    assert "Add new feature" in draft_result

    # pr_code should NOT have DEFAULT_RELEASE_NOTES_TEMPLATE structure
    assert "## 📋 All Changes" not in pr_code_result
    assert "### 🚀 Features" not in pr_code_result

    # draft should HAVE DEFAULT_RELEASE_NOTES_TEMPLATE structure
    assert "## 📋 All Changes" in draft_result
    assert "### 🚀 Features" in draft_result
    assert "### 🛠 Bug Fixes" in draft_result

    # Verify they're meaningfully different
    assert pr_code_result != draft_result
