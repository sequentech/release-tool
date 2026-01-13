# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for the default output_template structure."""

import pytest
from datetime import datetime
from release_tool.policies import ReleaseNoteGenerator
from release_tool.config import Config
from release_tool.models import ReleaseNote, Author


def test_default_template_structure():
    """Test that the default output_template has the expected structure."""
    # Use default config (no customization)
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}]
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)

    # Create test notes with all features
    author1 = Author(name="Alice", username="alice", company="Acme Corp")
    author2 = Author(name="Bob", username="bob")

    notes = [
        # Breaking change with description
        ReleaseNote(
            title="Breaking: Remove old API",
            category="💥 Breaking Changes",
            labels=["breaking-change"],
            authors=[author1],
            pr_numbers=[100],
            url="https://github.com/test/repo/pull/100",
            description="The old API has been completely removed in favor of the new v2 API."
        ),
        # Feature with migration notes
        ReleaseNote(
            title="Add new authentication system",
            category="🚀 Features",
            labels=["feature"],
            authors=[author1, author2],
            pr_numbers=[101],
            url="https://github.com/test/repo/pull/101",
            description="Implemented OAuth2 authentication with JWT tokens.",
            migration_notes="Run `python manage.py migrate_auth` to update your database schema."
        ),
        # Bug fix with description
        ReleaseNote(
            title="Fix login redirect",
            category="🛠 Bug Fixes",
            labels=["bug"],
            authors=[author2],
            pr_numbers=[102],
            url="https://github.com/test/repo/pull/102",
            description="Fixed an issue where users were redirected to the wrong page after login."
        ),
        # Feature without description
        ReleaseNote(
            title="Improve performance",
            category="🚀 Features",
            labels=["feature"],
            authors=[author1],
            pr_numbers=[103],
            url="https://github.com/test/repo/pull/103"
        ),
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Note: Title "# Release 1.0.0" is no longer in the release template
    # It appears in the GitHub release UI title instead

    # Verify structure: Breaking Changes Descriptions section
    assert "## 💥 Breaking Changes" in output
    assert "### Breaking: Remove old API" in output
    assert "The old API has been completely removed" in output

    # Verify structure: Migration Guide section
    assert "## 🔄 Migrations" in output
    assert "### Add new authentication system" in output
    assert "Run `python manage.py migrate_auth`" in output

    # Verify structure: Detailed Descriptions section
    assert "## 📝 Highlights" in output
    # Should include feature and bug fix descriptions (but NOT breaking changes)
    assert "### Add new authentication system" in output
    assert "Implemented OAuth2 authentication" in output
    assert "### Fix login redirect" in output
    assert "Fixed an issue where users were redirected" in output
    # Breaking change description should NOT appear in this section
    # (it appears in Breaking Changes Descriptions section instead)

    # Verify structure: All Changes section
    assert "## 📋 All Changes" in output
    assert "### 💥 Breaking Changes" in output
    assert "### 🚀 Features" in output
    assert "### 🛠 Bug Fixes" in output

    # Verify all notes appear in All Changes
    assert "Breaking: Remove old API" in output
    assert "Add new authentication system" in output
    assert "Fix login redirect" in output
    assert "Improve performance" in output


def test_default_template_with_alias():
    """Test that category alias works in default template."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}]
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)

    # Check that categories have aliases
    breaking_cat = next(c for c in config.release_notes.categories if c.name == "💥 Breaking Changes")
    assert breaking_cat.alias == "breaking"

    features_cat = next(c for c in config.release_notes.categories if c.name == "🚀 Features")
    assert features_cat.alias == "features"


def test_default_template_skips_empty_sections():
    """Test that empty sections are not shown."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}]
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)

    # Create notes without breaking changes or migrations
    author = Author(name="Alice", username="alice")
    notes = [
        ReleaseNote(
            title="Add feature",
            category="🚀 Features",
            labels=["feature"],
            authors=[author],
            pr_numbers=[100]
        ),
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Should NOT have breaking changes section (no breaking changes)
    assert "## 💥 Breaking Changes" not in output

    # Should NOT have migrations section (no migration notes)
    assert "## 🔄 Migrations" not in output

    # Should NOT have detailed descriptions section (no descriptions)
    assert "## 📝 Highlights" not in output

    # Should still have All Changes section
    assert "## 📋 All Changes" in output
    assert "Add feature" in output


def test_default_template_categories_ordering():
    """Test that categories appear in the correct order."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}]
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)

    # Create notes in reverse order
    author = Author(name="Alice", username="alice")
    notes = [
        ReleaseNote(
            title="Update docs",
            category="📖 Documentation",
            labels=["docs"],
            authors=[author]
        ),
        ReleaseNote(
            title="Fix bug",
            category="🛠 Bug Fixes",
            labels=["bug"],
            authors=[author]
        ),
        ReleaseNote(
            title="Add feature",
            category="🚀 Features",
            labels=["feature"],
            authors=[author]
        ),
        ReleaseNote(
            title="Breaking change",
            category="💥 Breaking Changes",
            labels=["breaking"],
            authors=[author]
        ),
    ]

    generator = ReleaseNoteGenerator(config)
    grouped = generator.group_by_category(notes)
    output = generator.format_markdown(grouped, "1.0.0")

    # Find positions in output
    breaking_pos = output.find("### 💥 Breaking Changes")
    features_pos = output.find("### 🚀 Features")
    bugfixes_pos = output.find("### 🛠 Bug Fixes")
    docs_pos = output.find("### 📖 Documentation")

    # Verify order: Breaking < Features < Bug Fixes < Documentation
    assert breaking_pos < features_pos
    assert features_pos < bugfixes_pos
    assert bugfixes_pos < docs_pos


def test_default_categories_match_backup_config():
    """Test that default categories match the backup config."""
    config_dict = {
        "repository": {
            "code_repos": [{"link": "test/repo", "alias": "repo"}]
        }
    }
    config = Config.from_dict(config_dict)

    category_names = [c.name for c in config.release_notes.categories]

    # Should match backup config categories
    assert "💥 Breaking Changes" in category_names
    assert "🚀 Features" in category_names
    assert "🛠 Bug Fixes" in category_names
    assert "📖 Documentation" in category_names
    assert "🛡 Security Updates" in category_names

    # CRITICAL: Must have a category with alias="other" for fallback
    # The category name can be anything (e.g., "Other", "Miscellaneous"),
    # but the alias must be "other" for the tool to detect it as the fallback category
    assert "Other" in category_names

    # Verify the "Other" category configuration
    other_cat = next(c for c in config.release_notes.categories if c.name == "Other")
    assert other_cat.labels == []  # Should have no labels (catches all unmatched)
    assert other_cat.order == 99  # Should be last in order
    assert other_cat.alias == "other"  # REQUIRED - tool detects fallback by this alias

    # Check labels
    features_cat = next(c for c in config.release_notes.categories if c.name == "🚀 Features")
    assert "feature" in features_cat.labels
    assert "enhancement" in features_cat.labels
    assert "feat" in features_cat.labels

    bugfixes_cat = next(c for c in config.release_notes.categories if c.name == "🛠 Bug Fixes")
    assert "bug" in bugfixes_cat.labels
    assert "fix" in bugfixes_cat.labels
    assert "bugfix" in bugfixes_cat.labels
    assert "hotfix" in bugfixes_cat.labels
