"""Tests for Git operations."""

import pytest
from release_tool.models import SemanticVersion
from release_tool.git_ops import find_comparison_version


class TestFindComparisonVersion:
    """Tests for version comparison logic."""

    def test_final_version_compares_to_previous_final(self):
        target = SemanticVersion.parse("2.0.0")
        available = [
            SemanticVersion.parse("1.0.0"),
            SemanticVersion.parse("1.5.0"),
            SemanticVersion.parse("1.9.0"),
            SemanticVersion.parse("2.0.0-rc.1")
        ]

        result = find_comparison_version(target, available)
        assert result == SemanticVersion.parse("1.9.0")

    def test_rc_compares_to_previous_rc_of_same_version(self):
        target = SemanticVersion.parse("2.0.0-rc.2")
        available = [
            SemanticVersion.parse("1.9.0"),
            SemanticVersion.parse("2.0.0-rc.1"),
            SemanticVersion.parse("2.0.0-rc.0")
        ]

        result = find_comparison_version(target, available)
        assert result == SemanticVersion.parse("2.0.0-rc.1")

    def test_rc_compares_to_previous_final_if_no_rc(self):
        target = SemanticVersion.parse("2.0.0-rc.1")
        available = [
            SemanticVersion.parse("1.0.0"),
            SemanticVersion.parse("1.5.0")
        ]

        result = find_comparison_version(target, available)
        assert result == SemanticVersion.parse("1.5.0")

    def test_first_version_has_no_comparison(self):
        target = SemanticVersion.parse("1.0.0")
        available = [SemanticVersion.parse("1.0.0")]

        result = find_comparison_version(target, available)
        assert result is None

    def test_returns_none_if_no_earlier_versions(self):
        target = SemanticVersion.parse("2.0.0")
        available = [SemanticVersion.parse("3.0.0")]

        result = find_comparison_version(target, available)
        assert result is None
