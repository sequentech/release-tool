"""Tests for configuration management."""

import os
import pytest
from pathlib import Path
from release_tool.config import Config, load_config


def test_config_from_dict():
    """Test creating config from dictionary."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        },
        "github": {
            "token": "test_token"
        }
    }
    config = Config.from_dict(config_dict)
    assert config.repository.code_repo == "test/repo"
    assert config.github.token == "test_token"


def test_load_from_file(tmp_path):
    """Test loading config from TOML file."""
    config_file = tmp_path / "test_config.toml"
    config_content = """
config_version = "1.2"

[repository]
code_repo = "owner/repo"
default_branch = "main"

[github]
token = "fake-token"

[version_policy]
tag_prefix = "release-"
"""
    config_file.write_text(config_content)

    config = Config.from_file(str(config_file))
    assert config.repository.code_repo == "owner/repo"
    assert config.version_policy.tag_prefix == "release-"


def test_env_var_override(monkeypatch):
    """Test GitHub token override from environment."""
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")

    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        }
    }
    config = Config.from_dict(config_dict)
    assert config.github.token == "env-token"


def test_category_map():
    """Test category mapping generation."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        }
    }
    config = Config.from_dict(config_dict)

    category_map = config.get_category_map()
    assert "🚀 Features" in category_map
    assert "🛠 Bug Fixes" in category_map
    assert "feature" in category_map["🚀 Features"]


def test_ordered_categories():
    """Test category ordering."""
    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        }
    }
    config = Config.from_dict(config_dict)

    categories = config.get_ordered_categories()
    assert isinstance(categories, list)
    assert len(categories) > 0


def test_category_label_matching_no_prefix():
    """Test label matching without prefix (matches any source)."""
    from release_tool.config import CategoryConfig

    category = CategoryConfig(
        name="Test",
        labels=["bug", "feature"],
        order=1
    )

    # Should match from either source
    assert category.matches_label("bug", "pr")
    assert category.matches_label("bug", "ticket")
    assert category.matches_label("feature", "pr")
    assert category.matches_label("feature", "ticket")
    assert not category.matches_label("other", "pr")


def test_category_label_matching_with_pr_prefix():
    """Test label matching with pr: prefix."""
    from release_tool.config import CategoryConfig

    category = CategoryConfig(
        name="Test",
        labels=["pr:bug", "feature"],
        order=1
    )

    # pr:bug should only match from PRs
    assert category.matches_label("bug", "pr")
    assert not category.matches_label("bug", "ticket")

    # feature (no prefix) should match from either
    assert category.matches_label("feature", "pr")
    assert category.matches_label("feature", "ticket")


def test_category_label_matching_with_ticket_prefix():
    """Test label matching with ticket: prefix."""
    from release_tool.config import CategoryConfig

    category = CategoryConfig(
        name="Test",
        labels=["ticket:critical", "normal"],
        order=1
    )

    # ticket:critical should only match from tickets
    assert not category.matches_label("critical", "pr")
    assert category.matches_label("critical", "ticket")

    # normal (no prefix) should match from either
    assert category.matches_label("normal", "pr")
    assert category.matches_label("normal", "ticket")
