# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for documentation release version policy."""

import pytest
from release_tool.models import SemanticVersion
from release_tool.git_ops import find_comparison_version_for_docs


class TestDocumentationReleaseVersionPolicy:
    """Tests for documentation_release_version_policy config option."""

    def test_final_only_rc_compares_to_previous_final(self):
        """In final-only mode, RCs should compare to previous final version."""
        target = SemanticVersion.parse("11.0.0-rc.1")
        available = [
            SemanticVersion.parse("10.5.0"),
            SemanticVersion.parse("10.9.0"),
            SemanticVersion.parse("11.0.0-rc.0")
        ]

        result = find_comparison_version_for_docs(target, available, policy="final-only")

        # Should skip 11.0.0-rc.0 and compare to 10.9.0 (previous final)
        assert result == SemanticVersion.parse("10.9.0")

    def test_final_only_rc_without_previous_rc(self):
        """In final-only mode, first RC should compare to previous final."""
        target = SemanticVersion.parse("11.0.0-rc.0")
        available = [
            SemanticVersion.parse("10.0.0"),
            SemanticVersion.parse("10.5.0")
        ]

        result = find_comparison_version_for_docs(target, available, policy="final-only")

        # Should compare to 10.5.0 (previous final)
        assert result == SemanticVersion.parse("10.5.0")

    def test_final_only_final_version_compares_to_previous_final(self):
        """In final-only mode, final versions should compare to previous final."""
        target = SemanticVersion.parse("11.0.0")
        available = [
            SemanticVersion.parse("10.5.0"),
            SemanticVersion.parse("11.0.0-rc.0"),
            SemanticVersion.parse("11.0.0-rc.1")
        ]

        result = find_comparison_version_for_docs(target, available, policy="final-only")

        # Should skip RCs and compare to 10.5.0 (previous final)
        assert result == SemanticVersion.parse("10.5.0")

    def test_include_rcs_rc_uses_standard_comparison(self):
        """In include-rcs mode, RCs should use standard comparison logic."""
        target = SemanticVersion.parse("11.0.0-rc.2")
        available = [
            SemanticVersion.parse("10.5.0"),
            SemanticVersion.parse("11.0.0-rc.0"),
            SemanticVersion.parse("11.0.0-rc.1")
        ]

        result = find_comparison_version_for_docs(target, available, policy="include-rcs")

        # Should compare to 11.0.0-rc.1 (previous RC of same version)
        assert result == SemanticVersion.parse("11.0.0-rc.1")

    def test_include_rcs_first_rc_compares_to_previous_final(self):
        """In include-rcs mode, first RC should compare to previous final."""
        target = SemanticVersion.parse("11.0.0-rc.0")
        available = [
            SemanticVersion.parse("10.0.0"),
            SemanticVersion.parse("10.5.0")
        ]

        result = find_comparison_version_for_docs(target, available, policy="include-rcs")

        # Should compare to 10.5.0 (previous final)
        assert result == SemanticVersion.parse("10.5.0")

    def test_include_rcs_final_version_compares_to_previous_final(self):
        """In include-rcs mode, final versions should compare to previous final (complete changelog)."""
        target = SemanticVersion.parse("11.0.0")
        available = [
            SemanticVersion.parse("10.5.0"),
            SemanticVersion.parse("11.0.0-rc.0"),
            SemanticVersion.parse("11.0.0-rc.1")
        ]

        result = find_comparison_version_for_docs(target, available, policy="include-rcs")

        # Should skip RCs and compare to 10.5.0 (previous final) for complete changelog
        assert result == SemanticVersion.parse("10.5.0")

    def test_no_previous_versions_returns_none(self):
        """When there are no previous versions, should return None."""
        target = SemanticVersion.parse("1.0.0")
        available = [SemanticVersion.parse("1.0.0")]

        result_final_only = find_comparison_version_for_docs(target, available, policy="final-only")
        result_include_rcs = find_comparison_version_for_docs(target, available, policy="include-rcs")

        assert result_final_only is None
        assert result_include_rcs is None

    def test_final_only_multiple_rcs(self):
        """In final-only mode, should skip all RCs and find previous final."""
        target = SemanticVersion.parse("11.0.0-rc.5")
        available = [
            SemanticVersion.parse("10.0.0"),
            SemanticVersion.parse("11.0.0-rc.0"),
            SemanticVersion.parse("11.0.0-rc.1"),
            SemanticVersion.parse("11.0.0-rc.2"),
            SemanticVersion.parse("11.0.0-rc.3"),
            SemanticVersion.parse("11.0.0-rc.4")
        ]

        result = find_comparison_version_for_docs(target, available, policy="final-only")

        # Should skip all RCs and compare to 10.0.0 (previous final)
        assert result == SemanticVersion.parse("10.0.0")

    def test_include_rcs_finds_latest_rc_of_same_version(self):
        """In include-rcs mode, should find the latest RC of the same version."""
        target = SemanticVersion.parse("11.0.0-rc.5")
        available = [
            SemanticVersion.parse("10.0.0"),
            SemanticVersion.parse("11.0.0-rc.0"),
            SemanticVersion.parse("11.0.0-rc.1"),
            SemanticVersion.parse("11.0.0-rc.2"),
            SemanticVersion.parse("11.0.0-rc.3"),
            SemanticVersion.parse("11.0.0-rc.4")
        ]

        result = find_comparison_version_for_docs(target, available, policy="include-rcs")

        # Should compare to 11.0.0-rc.4 (previous RC of same version)
        assert result == SemanticVersion.parse("11.0.0-rc.4")

    def test_patch_rc_in_final_only_mode(self):
        """Test patch version RC in final-only mode."""
        target = SemanticVersion.parse("11.0.1-rc.0")
        available = [
            SemanticVersion.parse("11.0.0"),
            SemanticVersion.parse("10.9.0")
        ]

        result = find_comparison_version_for_docs(target, available, policy="final-only")

        # Should compare to 11.0.0 (previous final)
        assert result == SemanticVersion.parse("11.0.0")

    def test_minor_rc_in_final_only_mode(self):
        """Test minor version RC in final-only mode."""
        target = SemanticVersion.parse("11.1.0-rc.0")
        available = [
            SemanticVersion.parse("11.0.0"),
            SemanticVersion.parse("11.0.5"),
            SemanticVersion.parse("10.9.0")
        ]

        result = find_comparison_version_for_docs(target, available, policy="final-only")

        # Should compare to 11.0.5 (previous final)
        assert result == SemanticVersion.parse("11.0.5")

    def test_default_policy_is_final_only(self):
        """Test that default policy is 'final-only'."""
        target = SemanticVersion.parse("11.0.0-rc.1")
        available = [
            SemanticVersion.parse("10.5.0"),
            SemanticVersion.parse("11.0.0-rc.0")
        ]

        # Call without policy parameter (should default to "final-only")
        result = find_comparison_version_for_docs(target, available)

        # Should compare to 10.5.0 (previous final) as per final-only mode
        assert result == SemanticVersion.parse("10.5.0")
