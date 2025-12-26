# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Git operations for the release tool."""

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from git import Repo, Commit as GitCommit
from .models import Commit, SemanticVersion
from .template_utils import render_template, TemplateError


class GitOperations:
    """Git operations wrapper."""

    def __init__(self, repo_path: str):
        """Initialize with path to git repository."""
        self.repo_path = Path(repo_path)
        self.repo = Repo(str(self.repo_path))

    def get_tags(self) -> List[str]:
        """Get all tags in the repository."""
        return [tag.name for tag in self.repo.tags]

    def get_version_tags(self) -> List[SemanticVersion]:
        """Get all version tags, parsed as semantic versions."""
        versions = []
        for tag in self.get_tags():
            try:
                version = SemanticVersion.parse(tag)
                versions.append(version)
            except ValueError:
                # Skip non-semver tags
                continue
        return sorted(versions)

    def get_latest_tag(self, final_only: bool = False) -> Optional[str]:
        """
        Get the most recent tag by semantic version (not by commit date).

        Args:
            final_only: If True, only considers final releases (excludes prereleases)

        Returns:
            Latest tag name, or None if no tags found
        """
        try:
            # Get all version tags sorted by semantic version
            versions = self.get_version_tags()
            if not versions:
                return None

            # Filter to final versions only if requested
            if final_only:
                versions = [v for v in versions if v.is_final()]
                if not versions:
                    return None

            # Return the highest semantic version
            latest = max(versions)
            return latest.to_string(include_v=True) if latest else None
        except Exception:
            return None

    def get_commits_between_refs(
        self, base_ref: str, head_ref: str = "HEAD"
    ) -> List[GitCommit]:
        """Get commits between two refs."""
        try:
            commit_range = f"{base_ref}..{head_ref}"
            commits = list(self.repo.iter_commits(commit_range))
            return commits
        except Exception as e:
            raise ValueError(f"Failed to get commits between {base_ref} and {head_ref}: {e}")

    def get_commits_for_version_range(
        self, from_version: SemanticVersion, to_version: SemanticVersion
    ) -> List[GitCommit]:
        """Get commits between two versions."""
        from_tag = self._find_tag_for_version(from_version)
        to_tag = self._find_tag_for_version(to_version)

        if not from_tag:
            raise ValueError(f"Tag not found for version {from_version.to_string()}")
        if not to_tag:
            raise ValueError(f"Tag not found for version {to_version.to_string()}")

        return self.get_commits_between_refs(from_tag, to_tag)

    def _find_tag_for_version(self, version: SemanticVersion) -> Optional[str]:
        """Find tag name for a given version."""
        version_str = version.to_string()
        version_str_with_v = version.to_string(include_v=True)

        for tag in self.repo.tags:
            if tag.name == version_str or tag.name == version_str_with_v:
                return tag.name
        return None

    def extract_pr_number_from_commit(self, commit: GitCommit) -> Optional[int]:
        """Extract PR number from commit message."""
        # Common patterns:
        # - "Merge pull request #123 from..."
        # - "... (#123)"
        # - "PR #123:"
        patterns = [
            r'[Mm]erge pull request #(\d+)',
            r'\(#(\d+)\)',
            r'[Pp][Rr]\s*#(\d+)',
        ]

        message = commit.message
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return int(match.group(1))
        return None

    def commit_to_model(self, git_commit: GitCommit, repo_id: int) -> Commit:
        """Convert GitPython commit to our model."""
        from .models import Author

        pr_number = self.extract_pr_number_from_commit(git_commit)

        # Create Author from git commit author info
        # Note: GitPython provides GitAuthor which has name and email
        # We don't have GitHub username here, but it may be enriched later
        # via PR author lookup or GitHub API
        author = Author(
            name=git_commit.author.name if git_commit.author else "Unknown",
            email=git_commit.author.email if git_commit.author else None
        )

        return Commit(
            sha=git_commit.hexsha,
            repo_id=repo_id,
            message=git_commit.message,
            author=author,
            date=datetime.fromtimestamp(git_commit.committed_date),
            pr_number=pr_number
        )

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        return self.repo.active_branch.name

    def get_commit_by_sha(self, sha: str) -> Optional[GitCommit]:
        """Get a specific commit by SHA."""
        try:
            return self.repo.commit(sha)
        except Exception:
            return None

    def get_default_branch(self) -> str:
        """Get the default branch (usually main or master)."""
        try:
            # Try to get from remote
            origin = self.repo.remote('origin')
            return origin.refs.HEAD.ref.remote_head
        except Exception:
            # Fallback to common defaults
            for branch in ['main', 'master']:
                try:
                    self.repo.branches[branch]
                    return branch
                except Exception:
                    continue
            # Return current branch as last resort
            return self.get_current_branch()

    def fetch_remote_refs(self, remote: str = "origin") -> None:
        """
        Fetch remote references to ensure we have up-to-date remote branch info.
        
        Args:
            remote: Remote name (default: "origin")
        """
        try:
            self.repo.git.fetch(remote)
        except Exception as e:
            # Non-fatal - remote might not exist in tests or offline scenarios
            pass

    def get_all_branches(self, remote: bool = False) -> List[str]:
        """Get all branch names (local or remote)."""
        if remote:
            try:
                origin = self.repo.remote('origin')
                return [ref.remote_head for ref in origin.refs if ref.remote_head != 'HEAD']
            except Exception:
                return []
        else:
            return [branch.name for branch in self.repo.branches]

    def branch_exists(self, branch_name: str, remote: bool = False) -> bool:
        """Check if a branch exists (locally or remotely)."""
        branches = self.get_all_branches(remote=remote)
        return branch_name in branches

    def create_branch(self, branch_name: str, start_point: str = "HEAD") -> None:
        """Create a new branch from a starting point."""
        if self.branch_exists(branch_name):
            raise ValueError(f"Branch {branch_name} already exists")

        self.repo.create_head(branch_name, start_point)

    def checkout_branch(self, branch_name: str, create: bool = False) -> None:
        """Checkout a branch, optionally creating it first."""
        if create and not self.branch_exists(branch_name):
            self.create_branch(branch_name)

        self.repo.git.checkout(branch_name)

    def push_branch(self, branch_name: str, remote: str = "origin", set_upstream: bool = True) -> None:
        """
        Push a branch to remote repository.

        Args:
            branch_name: Name of the branch to push
            remote: Remote name (default: "origin")
            set_upstream: Whether to set upstream tracking (default: True)
        """
        if set_upstream:
            self.repo.git.push("-u", remote, branch_name)
        else:
            self.repo.git.push(remote, branch_name)

    def create_tag(self, tag_name: str, ref: str = "HEAD", message: Optional[str] = None) -> None:
        """
        Create a git tag.

        Args:
            tag_name: Name of the tag to create
            ref: Reference to tag (default: "HEAD")
            message: Optional tag message for annotated tags
        """
        if message:
            self.repo.create_tag(tag_name, ref=ref, message=message)
        else:
            self.repo.create_tag(tag_name, ref=ref)

    def push_tag(self, tag_name: str, remote: str = "origin", force: bool = False) -> None:
        """
        Push a tag to remote repository.

        Args:
            tag_name: Name of the tag to push
            remote: Remote name (default: "origin")
            force: Whether to force push the tag (default: False)
        """
        if force:
            self.repo.git.push(remote, tag_name, "--force")
        else:
            self.repo.git.push(remote, tag_name)

    def tag_exists(self, tag_name: str, remote: bool = False) -> bool:
        """
        Check if a tag exists.

        Args:
            tag_name: Name of the tag to check
            remote: Check remote tags if True, local if False

        Returns:
            True if tag exists, False otherwise
        """
        if remote:
            try:
                self.repo.git.ls_remote("--tags", "origin", tag_name)
                return True
            except Exception:
                return False
        else:
            return tag_name in [tag.name for tag in self.repo.tags]

    def find_release_branches(self, major: int, minor: Optional[int] = None) -> List[str]:
        """
        Find release branches matching a pattern.

        Args:
            major: Major version number
            minor: Optional minor version number

        Returns:
            List of branch names matching the pattern
        """
        all_branches = self.get_all_branches() + self.get_all_branches(remote=True)
        all_branches = list(set(all_branches))  # Deduplicate

        if minor is not None:
            pattern = f"release/{major}.{minor}"
            return [b for b in all_branches if b == pattern or b == f"origin/{pattern}"]
        else:
            pattern_prefix = f"release/{major}."
            matches = []
            for branch in all_branches:
                clean_branch = branch.replace("origin/", "")
                if clean_branch.startswith(pattern_prefix):
                    matches.append(clean_branch)
            return matches

    def get_latest_release_branch(self, major: int) -> Optional[str]:
        """
        Get the most recent release branch for a given major version.

        Args:
            major: Major version number

        Returns:
            Branch name of the latest release, or None if no release branches exist
        """
        branches = self.find_release_branches(major)
        if not branches:
            return None

        # Extract minor versions and sort
        branch_versions = []
        for branch in branches:
            # Parse release/X.Y format
            match = re.match(r'release/(\d+)\.(\d+)', branch)
            if match:
                branch_major, branch_minor = int(match.group(1)), int(match.group(2))
                if branch_major == major:
                    branch_versions.append((branch_minor, branch))

        if not branch_versions:
            return None

        # Return branch with highest minor version
        branch_versions.sort(reverse=True)
        return branch_versions[0][1]


def determine_release_branch_strategy(
    version: SemanticVersion,
    git_ops: "GitOperations",
    available_versions: List[SemanticVersion],
    branch_template: str = "release/{major}.{minor}",
    default_branch: str = "main",
    branch_from_previous: bool = True
) -> Tuple[str, str, bool]:
    """
    Determine the release branch name and source branch for a version.

    Args:
        version: Target version
        git_ops: GitOperations instance
        available_versions: List of existing versions
        branch_template: Template for branch names
        default_branch: Default branch (e.g., "main")
        branch_from_previous: Whether to branch from previous release

    Returns:
        Tuple of (release_branch_name, source_branch, should_create_branch)
    """
    # Format release branch name using Jinja2 template
    template_context = {
        'major': str(version.major),
        'minor': str(version.minor),
        'patch': str(version.patch)
    }
    try:
        release_branch = render_template(branch_template, template_context)
    except TemplateError as e:
        # Fall back to simple string if template rendering fails
        # This maintains backwards compatibility
        release_branch = f"release/{version.major}.{version.minor}"

    # Check if this branch already exists
    branch_exists = git_ops.branch_exists(release_branch) or git_ops.branch_exists(release_branch, remote=True)

    # Check if this is the first release for this major.minor
    same_version_releases = [
        v for v in available_versions
        if v.major == version.major and v.minor == version.minor
    ]

    # Determine source branch
    source_branch = default_branch  # Default fallback

    if same_version_releases:
        # Not the first release for this version - use existing release branch
        source_branch = release_branch
        should_create = False
    else:
        # First release for this major.minor - need to determine source
        should_create = not branch_exists

        if version.minor == 0:
            # New major version - branch from default branch
            source_branch = default_branch
        elif branch_from_previous:
            # New minor version - try to branch from previous minor's release branch
            prev_release_branch = git_ops.get_latest_release_branch(version.major)

            if prev_release_branch:
                source_branch = prev_release_branch
            else:
                # No previous release branch found - check if there are any releases for this major
                same_major_releases = [
                    v for v in available_versions
                    if v.major == version.major and v.is_final()
                ]

                if same_major_releases:
                    # There are releases but no branches - branch from default
                    source_branch = default_branch
                else:
                    # New major version - branch from default
                    source_branch = default_branch
        else:
            # Not branching from previous - use default branch
            source_branch = default_branch

    return (release_branch, source_branch, should_create)


def find_comparison_version(
    target_version: SemanticVersion,
    available_versions: List[SemanticVersion]
) -> Optional[SemanticVersion]:
    """
    Find the appropriate version to compare against based on the target version.

    Rules:
    - Release candidates compare to previous RC of same version, or previous final version
    - Final versions compare to previous final version
    - Betas/alphas compare to previous prerelease of same major.minor, or previous final
    """
    target_type = target_version.get_type()

    # Filter and sort versions before the target
    earlier_versions = [v for v in available_versions if v < target_version]
    if not earlier_versions:
        return None

    earlier_versions = sorted(earlier_versions, reverse=True)

    # For release candidates, try to find previous RC of same version first
    if target_type == target_version.get_type().RELEASE_CANDIDATE:
        # Look for RCs of the same major.minor.patch
        same_version_rcs = [
            v for v in earlier_versions
            if (v.major == target_version.major and
                v.minor == target_version.minor and
                v.patch == target_version.patch and
                v.prerelease is not None and
                v.prerelease.startswith('rc'))
        ]
        if same_version_rcs:
            return same_version_rcs[0]

    # For final versions or if no matching RC found, look for previous final version
    if target_type == target_version.get_type().FINAL or target_version.prerelease:
        # If this is a final version, find the previous final version
        final_versions = [v for v in earlier_versions if v.is_final()]
        if final_versions:
            return final_versions[0]

        # If no final version exists, return the most recent version
        return earlier_versions[0]

    return earlier_versions[0] if earlier_versions else None


def find_comparison_version_for_docs(
    target_version: SemanticVersion,
    available_versions: List[SemanticVersion],
    policy: str = "final-only"
) -> Optional[SemanticVersion]:
    """
    Find the appropriate version to compare against for documentation generation.

    This function implements the release_version_policy behavior (per pr_code template):
    - 'final-only': RCs compare against previous final version (not other RCs)
    - 'include-rcs': Uses standard comparison logic

    Args:
        target_version: The version being generated
        available_versions: List of available versions
        policy: Release version policy ('final-only' or 'include-rcs')

    Returns:
        Version to compare against, or None if no suitable version found

    Rules:
    - 'final-only' mode:
        * RC versions: Compare to previous final version (ignore RCs)
        * Final versions: Compare to previous final version
    - 'include-rcs' mode:
        * Uses standard comparison logic (delegates to find_comparison_version)
    """
    target_type = target_version.get_type()

    # Filter and sort versions before the target
    earlier_versions = [v for v in available_versions if v < target_version]
    if not earlier_versions:
        return None

    earlier_versions = sorted(earlier_versions, reverse=True)

    # For 'include-rcs' mode, use standard comparison logic
    if policy == "include-rcs":
        return find_comparison_version(target_version, available_versions)

    # For 'final-only' mode:
    # Both RCs and final versions compare against previous final version
    if target_type == target_version.get_type().RELEASE_CANDIDATE or target_version.is_final():
        # Find the previous final version
        final_versions = [v for v in earlier_versions if v.is_final()]
        if final_versions:
            return final_versions[0]

        # If no final version exists, return the most recent version
        return earlier_versions[0] if earlier_versions else None

    # For other prerelease types (beta, alpha, etc.), use standard logic
    return find_comparison_version(target_version, available_versions)


def get_release_commit_range(
    git_ops: GitOperations,
    target_version: SemanticVersion,
    from_version: Optional[SemanticVersion] = None,
    head_ref: str = "HEAD"
) -> Tuple[Optional[SemanticVersion], List[GitCommit]]:
    """
    Get the commit range for a release.

    Args:
        git_ops: GitOperations instance
        target_version: The version being released
        from_version: Optional starting version (calculated if None)
        head_ref: Reference to use as the end of the range (default: HEAD)

    Returns: (comparison_version, commits)
    """
    available_versions = git_ops.get_version_tags()

    if from_version:
        comparison_version = from_version
    else:
        comparison_version = find_comparison_version(target_version, available_versions)

    if not comparison_version:
        # No previous version, get all commits up to target
        try:
            tag = git_ops._find_tag_for_version(target_version)
            if tag:
                # Get commits from beginning to target
                commits = list(git_ops.repo.iter_commits(tag))
            else:
                # Target tag doesn't exist yet, get all commits up to head_ref
                commits = list(git_ops.repo.iter_commits(head_ref))
            return None, commits
        except Exception:
            return None, []

    # Always use head_ref as the target for generating release notes
    # This ensures we generate notes from the release branch, not from existing tags
    from_tag = git_ops._find_tag_for_version(comparison_version)
    if from_tag:
        commits = git_ops.get_commits_between_refs(from_tag, head_ref)
        return comparison_version, commits
    return comparison_version, []
