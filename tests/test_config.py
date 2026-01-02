# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for configuration management."""

import os
import pytest
from pathlib import Path
from release_tool.config import Config, load_config


def test_config_from_dict(monkeypatch):
    """Test creating config from dictionary."""
    monkeypatch.setenv("GITHUB_TOKEN", "test_token")

    config_dict = {
        "repository": {
            "code_repo": "test/repo"
        }
    }
    config = Config.from_dict(config_dict)
    assert config.repository.code_repo == "test/repo"
    assert config.github.token == "test_token"


def test_load_from_file(tmp_path, monkeypatch):
    """Test loading config from TOML file."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    config_file = tmp_path / "test_config.toml"
    config_content = """
config_version = "1.5"

[repository]
code_repo = "owner/repo"
default_branch = "main"

[version_policy]
tag_prefix = "release-"
"""
    config_file.write_text(config_content)

    config = Config.from_file(str(config_file), auto_upgrade=True)
    assert config.repository.code_repo == "owner/repo"
    assert config.version_policy.tag_prefix == "release-"
    assert config.github.token == "fake-token"


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


def test_category_map(monkeypatch):
    """Test category mapping generation."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

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


def test_ordered_categories(monkeypatch):
    """Test category ordering."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

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
    assert category.matches_label("bug", "issue")
    assert category.matches_label("feature", "pr")
    assert category.matches_label("feature", "issue")
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
    assert not category.matches_label("bug", "issue")

    # feature (no prefix) should match from either
    assert category.matches_label("feature", "pr")
    assert category.matches_label("feature", "issue")


def test_category_label_matching_with_issue_prefix():
    """Test label matching with issue: prefix."""
    from release_tool.config import CategoryConfig

    category = CategoryConfig(
        name="Test",
        labels=["issue:critical", "normal"],
        order=1
    )

    # issue:critical should only match from issues
    assert not category.matches_label("critical", "pr")
    assert category.matches_label("critical", "issue")

    # normal (no prefix) should match from either
    assert category.matches_label("normal", "pr")
    assert category.matches_label("normal", "issue")


def test_invalid_inclusion_policy_raises_error(monkeypatch):
    """Test that invalid release_notes_inclusion_policy values raise ValidationError."""
    from pydantic import ValidationError
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    # Invalid value "invalid-type"
    with pytest.raises(ValidationError) as exc_info:
        Config.from_dict({
            "repository": {"code_repo": "test/repo"},
            "issue_policy": {
                "release_notes_inclusion_policy": ["issues", "invalid-type"]
            }
        })

    assert "release_notes_inclusion_policy" in str(exc_info.value)


def test_valid_inclusion_policy_values(monkeypatch):
    """Test that all valid inclusion policy values are accepted."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    # Test each valid value individually
    for value in ["issues", "pull-requests", "commits"]:
        config = Config.from_dict({
            "repository": {"code_repo": "test/repo"},
            "issue_policy": {
                "release_notes_inclusion_policy": [value]
            }
        })
        assert value in config.issue_policy.release_notes_inclusion_policy

    # Test all values together
    config = Config.from_dict({
        "repository": {"code_repo": "test/repo"},
        "issue_policy": {
            "release_notes_inclusion_policy": ["issues", "pull-requests", "commits"]
        }
    })
    assert len(config.issue_policy.release_notes_inclusion_policy) == 3


def test_default_inclusion_policy(monkeypatch):
    """Test that default inclusion policy is ["issues", "pull-requests"]."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    config = Config.from_dict({
        "repository": {"code_repo": "test/repo"}
    })

    assert config.issue_policy.release_notes_inclusion_policy == ["issues", "pull-requests"]


def test_missing_github_token_raises_error(monkeypatch):
    """Test that accessing token without GITHUB_TOKEN env var raises an error."""
    # Unset GITHUB_TOKEN if it exists
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    config = Config.from_dict({
        "repository": {"code_repo": "test/repo"}
    })

    # Accessing token should raise ValueError
    with pytest.raises(ValueError, match="GitHub token is required"):
        _ = config.github.token
