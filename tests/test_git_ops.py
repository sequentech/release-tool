"""Tests for Git operations."""

import pytest
from unittest.mock import Mock, MagicMock
from release_tool.models import SemanticVersion
from release_tool.git_ops import find_comparison_version, determine_release_branch_strategy


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


class TestReleaseBranchStrategy:
    """Tests for release branch strategy determination."""

    def create_mock_git_ops(self, existing_branches=None, remote_branches=None, latest_release_branch=None):
        """Create a mock GitOperations instance."""
        git_ops = Mock()

        # Mock branch_exists
        def branch_exists_side_effect(name, remote=False):
            branches = remote_branches if remote else existing_branches
            return branches and name in branches

        git_ops.branch_exists = Mock(side_effect=branch_exists_side_effect)
        git_ops.get_latest_release_branch = Mock(return_value=latest_release_branch)

        return git_ops

    def test_new_major_version_from_main(self):
        """Test new major version branches from main."""
        version = SemanticVersion.parse("9.0.0")
        available = [SemanticVersion.parse("8.5.0")]
        git_ops = self.create_mock_git_ops(existing_branches=[])

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="release/{major}.{minor}",
            default_branch="main"
        )

        assert branch == "release/9.0"
        assert source == "main"
        assert should_create is True

    def test_new_minor_from_previous_release(self):
        """Test new minor version branches from previous release branch."""
        version = SemanticVersion.parse("9.1.0")
        available = [SemanticVersion.parse("9.0.0")]
        git_ops = self.create_mock_git_ops(
            existing_branches=["release/9.0"],
            latest_release_branch="release/9.0"
        )

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="release/{major}.{minor}",
            default_branch="main",
            branch_from_previous=True
        )

        assert branch == "release/9.1"
        assert source == "release/9.0"
        assert should_create is True

    def test_new_minor_from_main_when_no_previous_branch(self):
        """Test new minor without previous branch falls back to main."""
        version = SemanticVersion.parse("9.1.0")
        available = [SemanticVersion.parse("9.0.0")]
        git_ops = self.create_mock_git_ops(
            existing_branches=[],
            latest_release_branch=None
        )

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="release/{major}.{minor}",
            default_branch="main",
            branch_from_previous=True
        )

        assert branch == "release/9.1"
        assert source == "main"
        assert should_create is True

    def test_existing_release_uses_same_branch(self):
        """Test that existing release (RC) uses existing branch."""
        version = SemanticVersion.parse("9.1.0-rc.1")
        available = [SemanticVersion.parse("9.1.0-rc.0")]  # Same version exists
        git_ops = self.create_mock_git_ops(existing_branches=["release/9.1"])

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="release/{major}.{minor}",
            default_branch="main"
        )

        assert branch == "release/9.1"
        assert source == "release/9.1"
        assert should_create is False

    def test_branch_from_previous_disabled(self):
        """Test that branch_from_previous=False uses main."""
        version = SemanticVersion.parse("9.1.0")
        available = [SemanticVersion.parse("9.0.0")]
        git_ops = self.create_mock_git_ops(
            existing_branches=["release/9.0"],
            latest_release_branch="release/9.0"
        )

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="release/{major}.{minor}",
            default_branch="main",
            branch_from_previous=False
        )

        assert branch == "release/9.1"
        assert source == "main"
        assert should_create is True

    def test_custom_branch_template(self):
        """Test custom branch naming template."""
        version = SemanticVersion.parse("9.1.0")
        available = []
        git_ops = self.create_mock_git_ops(existing_branches=[])

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="rel-{major}.{minor}.x",
            default_branch="develop"
        )

        assert branch == "rel-9.1.x"
        assert source == "develop"
        assert should_create is True

    def test_branch_exists_remotely(self):
        """Test detecting branch that exists remotely."""
        version = SemanticVersion.parse("9.1.0")
        available = []
        git_ops = self.create_mock_git_ops(
            existing_branches=[],
            remote_branches=["release/9.1"]
        )

        branch, source, should_create = determine_release_branch_strategy(
            version, git_ops, available,
            branch_template="release/{major}.{minor}",
            default_branch="main"
        )

        assert branch == "release/9.1"
        # Should not create if exists remotely
        assert should_create is False


class TestGetLatestTag:
    """Tests for get_latest_tag with final_only parameter."""

    def test_get_latest_tag_includes_rc_by_default(self):
        """Test that latest tag includes RCs by default."""
        from unittest.mock import Mock
        from release_tool.git_ops import GitOperations

        git_ops = GitOperations(".")
        git_ops.get_version_tags = Mock(return_value=[
            SemanticVersion.parse("9.2.0"),
            SemanticVersion.parse("9.3.0-rc.1"),
            SemanticVersion.parse("9.3.0-rc.6")
        ])

        latest = git_ops.get_latest_tag(final_only=False)
        assert latest == "v9.3.0-rc.6"

    def test_get_latest_tag_final_only(self):
        """Test that final_only=True excludes RCs."""
        from unittest.mock import Mock
        from release_tool.git_ops import GitOperations

        git_ops = GitOperations(".")
        git_ops.get_version_tags = Mock(return_value=[
            SemanticVersion.parse("9.2.0"),
            SemanticVersion.parse("9.3.0-rc.1"),
            SemanticVersion.parse("9.3.0-rc.6")
        ])

        latest = git_ops.get_latest_tag(final_only=True)
        assert latest == "v9.2.0"

    def test_get_latest_tag_no_final_versions(self):
        """Test that final_only=True returns None if no final versions."""
        from unittest.mock import Mock
        from release_tool.git_ops import GitOperations

        git_ops = GitOperations(".")
        git_ops.get_version_tags = Mock(return_value=[
            SemanticVersion.parse("9.3.0-rc.1"),
            SemanticVersion.parse("9.3.0-rc.6")
        ])

        latest = git_ops.get_latest_tag(final_only=True)
        assert latest is None
