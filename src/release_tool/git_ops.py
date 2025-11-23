"""Git operations for the release tool."""

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from git import Repo, Commit as GitCommit
from .models import Commit, SemanticVersion


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

    def get_latest_tag(self) -> Optional[str]:
        """Get the most recent tag."""
        try:
            return str(self.repo.git.describe('--tags', '--abbrev=0'))
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


def get_release_commit_range(
    git_ops: GitOperations,
    target_version: SemanticVersion,
    from_version: Optional[SemanticVersion] = None
) -> Tuple[Optional[SemanticVersion], List[GitCommit]]:
    """
    Get the commit range for a release.

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
                # Target tag doesn't exist yet, get all commits
                commits = list(git_ops.repo.iter_commits())
            return None, commits
        except Exception:
            return None, []

    try:
        commits = git_ops.get_commits_for_version_range(comparison_version, target_version)
        return comparison_version, commits
    except ValueError:
        # Target version tag doesn't exist yet, compare from comparison to HEAD
        from_tag = git_ops._find_tag_for_version(comparison_version)
        if from_tag:
            commits = git_ops.get_commits_between_refs(from_tag, "HEAD")
            return comparison_version, commits
        return comparison_version, []
