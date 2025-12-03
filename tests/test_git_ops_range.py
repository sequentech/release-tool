# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for release commit range calculation."""

import pytest
from unittest.mock import Mock, MagicMock
from release_tool.models import SemanticVersion
from release_tool.git_ops import get_release_commit_range

class TestGetReleaseCommitRange:
    """Tests for get_release_commit_range."""

    def test_uses_explicit_head_ref(self):
        """Test that get_release_commit_range uses the provided head_ref."""
        git_ops = Mock()
        git_ops.get_version_tags = Mock(return_value=[])
        git_ops._find_tag_for_version = Mock(return_value=None)
        
        # Mock iter_commits to return a list
        git_ops.repo.iter_commits = Mock(return_value=[])
        
        target_version = SemanticVersion.parse("9.2.0")
        
        # Call with explicit head_ref
        get_release_commit_range(git_ops, target_version, head_ref="release/9.2")
        
        # Verify iter_commits was called with the head_ref, not HEAD (implied or explicit)
        # The current implementation (buggy) ignores head_ref and uses HEAD or None (which implies HEAD)
        # The fix will make it use head_ref
        
        # We expect the call to be with "release/9.2"
        # Note: The current implementation calls iter_commits() with no args if tag not found
        # or iter_commits(tag) if tag found.
        # We are simulating tag not found (new release).
        
        # If the code is fixed, it should call iter_commits("release/9.2")
        # If the code is buggy, it calls iter_commits() (which means HEAD)
        
        # This assertion will fail on the buggy code if we were running it, 
        # but since we are mocking, we can just check what it was called with.
        
        # However, since I cannot run this test against the *actual* code without modifying it first 
        # (because the function signature doesn't accept head_ref yet), 
        # I will write this test to expect the *correct* behavior, and it will be valid once I update the code.
        
        git_ops.repo.iter_commits.assert_called_with("release/9.2")

    def test_uses_head_ref_with_comparison(self):
        """Test using head_ref when there is a comparison version."""
        git_ops = Mock()
        git_ops.get_version_tags = Mock(return_value=[SemanticVersion.parse("9.1.0")])
        git_ops._find_tag_for_version = Mock(return_value="v9.1.0")
        
        # Mock get_commits_for_version_range to raise ValueError (simulating target tag missing)
        git_ops.get_commits_for_version_range.side_effect = ValueError("Tag not found")
        
        # Mock get_commits_between_refs
        git_ops.get_commits_between_refs = Mock(return_value=[])
        
        target_version = SemanticVersion.parse("9.2.0")
        
        # Call with explicit head_ref
        get_release_commit_range(git_ops, target_version, head_ref="release/9.2")
        
        # Should call get_commits_between_refs with from_tag and head_ref
        git_ops.get_commits_between_refs.assert_called_with("v9.1.0", "release/9.2")
