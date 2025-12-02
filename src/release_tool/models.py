"""Data models for the release tool."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class VersionType(str, Enum):
    """Types of version releases."""
    FINAL = "final"
    RELEASE_CANDIDATE = "rc"
    BETA = "beta"
    ALPHA = "alpha"


class SemanticVersion(BaseModel):
    """Semantic version model."""
    major: int
    minor: int
    patch: int
    prerelease: Optional[str] = None

    @classmethod
    def parse(cls, version_str: str, allow_partial: bool = False) -> "SemanticVersion":
        """
        Parse a semantic version string.

        Args:
            version_str: Version string to parse (e.g., "1.2.3", "1.2.3-rc.1", "1.2")
            allow_partial: If True, allows partial versions like "1.2" (patch defaults to 0)

        Returns:
            SemanticVersion instance

        Raises:
            ValueError: If version string is invalid
        """
        import re
        # Remove leading 'v' if present
        version_str = version_str.lstrip('v')

        # Try full pattern first: major.minor.patch[-prerelease]
        full_pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$'
        match = re.match(full_pattern, version_str)

        if match:
            major, minor, patch, prerelease = match.groups()
            return cls(
                major=int(major),
                minor=int(minor),
                patch=int(patch),
                prerelease=prerelease
            )

        # Try partial pattern if allowed: major.minor
        if allow_partial:
            partial_pattern = r'^(\d+)\.(\d+)$'
            match = re.match(partial_pattern, version_str)
            if match:
                major, minor = match.groups()
                return cls(
                    major=int(major),
                    minor=int(minor),
                    patch=0,
                    prerelease=None
                )

        raise ValueError(f"Invalid semantic version: {version_str}")

    def to_string(self, include_v: bool = False) -> str:
        """Convert to string representation."""
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            version += f"-{self.prerelease}"
        if include_v:
            version = f"v{version}"
        return version

    def is_final(self) -> bool:
        """Check if this is a final release."""
        return self.prerelease is None

    def get_type(self) -> VersionType:
        """Get the version type."""
        if not self.prerelease:
            return VersionType.FINAL

        prerelease_lower = self.prerelease.lower()
        if prerelease_lower.startswith('rc'):
            return VersionType.RELEASE_CANDIDATE
        elif prerelease_lower.startswith('beta'):
            return VersionType.BETA
        elif prerelease_lower.startswith('alpha'):
            return VersionType.ALPHA

        return VersionType.FINAL

    def __lt__(self, other: "SemanticVersion") -> bool:
        """Compare versions."""
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        if self.patch != other.patch:
            return self.patch < other.patch

        # Handle prerelease comparison
        if self.prerelease is None and other.prerelease is None:
            return False
        if self.prerelease is None:
            return False  # Final version is greater
        if other.prerelease is None:
            return True  # Prerelease is less than final

        return self.prerelease < other.prerelease

    def __eq__(self, other: object) -> bool:
        """Check equality."""
        if not isinstance(other, SemanticVersion):
            return False
        return (self.major == other.major and
                self.minor == other.minor and
                self.patch == other.patch and
                self.prerelease == other.prerelease)

    def __le__(self, other: "SemanticVersion") -> bool:
        return self < other or self == other

    def __gt__(self, other: "SemanticVersion") -> bool:
        return not self <= other

    def __ge__(self, other: "SemanticVersion") -> bool:
        return not self < other

    def bump_major(self) -> "SemanticVersion":
        """Create a new version with major version bumped."""
        return SemanticVersion(major=self.major + 1, minor=0, patch=0)

    def bump_minor(self) -> "SemanticVersion":
        """Create a new version with minor version bumped."""
        return SemanticVersion(major=self.major, minor=self.minor + 1, patch=0)

    def bump_patch(self) -> "SemanticVersion":
        """Create a new version with patch version bumped."""
        return SemanticVersion(major=self.major, minor=self.minor, patch=self.patch + 1)

    def bump_rc(self, rc_number: int = 0) -> "SemanticVersion":
        """Create a new RC version."""
        return SemanticVersion(
            major=self.major,
            minor=self.minor,
            patch=self.patch,
            prerelease=f"rc.{rc_number}"
        )


class Repository(BaseModel):
    """Repository model."""
    id: Optional[int] = None
    owner: str
    name: str
    full_name: str = ""
    url: str = ""
    default_branch: str = "main"

    def __init__(self, **data):
        if 'full_name' not in data or not data['full_name']:
            data['full_name'] = f"{data['owner']}/{data['name']}"
        super().__init__(**data)


class Label(BaseModel):
    """GitHub label model."""
    name: str
    color: Optional[str] = None
    description: Optional[str] = None


class Author(BaseModel):
    """
    Author/contributor model with comprehensive information.

    Combines Git author info (name, email from commits) with GitHub user info
    (login, username, profile data). Not all fields are always available.
    """
    # Core identification (at least one should be present)
    name: Optional[str] = None  # Git author name (from commit)
    email: Optional[str] = None  # Git author email (from commit)
    username: Optional[str] = None  # GitHub login/username

    # GitHub user details (when available)
    github_id: Optional[int] = None  # GitHub user ID
    display_name: Optional[str] = None  # GitHub display name (may differ from git name)
    avatar_url: Optional[str] = None  # Profile picture URL
    profile_url: Optional[str] = None  # GitHub profile URL (html_url)

    # Extended profile info (optional, from GitHub API)
    company: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    blog: Optional[str] = None
    user_type: Optional[str] = None  # "User", "Bot", "Organization", etc.

    def get_identifier(self) -> str:
        """
        Get the best identifier for this author.

        Priority: username > name > email
        """
        if self.username:
            return self.username
        if self.name:
            return self.name
        if self.email:
            return self.email.split('@')[0]  # Use email prefix as fallback
        return "unknown"

    def get_display_name(self) -> str:
        """
        Get the best display name for this author.

        Priority: display_name > name > username > email
        """
        if self.display_name:
            return self.display_name
        if self.name:
            return self.name
        if self.username:
            return self.username
        if self.email:
            return self.email.split('@')[0]
        return "Unknown Author"

    def get_mention(self) -> str:
        """Get @ mention format (for GitHub comments, release notes, etc.)."""
        if self.username:
            return f"@{self.username}"
        return self.get_display_name()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for templates."""
        return {
            'name': self.name,
            'email': self.email,
            'username': self.username,
            'github_id': self.github_id,
            'display_name': self.display_name,
            'avatar_url': self.avatar_url,
            'profile_url': self.profile_url,
            'company': self.company,
            'location': self.location,
            'bio': self.bio,
            'blog': self.blog,
            'user_type': self.user_type,
            'identifier': self.get_identifier(),
            'mention': self.get_mention(),
            'full_display_name': self.get_display_name(),
        }


class PullRequest(BaseModel):
    """Pull request model."""
    id: Optional[int] = None
    repo_id: int
    number: int
    title: str
    body: Optional[str] = None
    state: str
    merged_at: Optional[datetime] = None
    author: Optional[Author] = None  # Changed from str to Author
    base_branch: Optional[str] = None
    head_branch: Optional[str] = None
    head_sha: Optional[str] = None
    labels: List[Label] = Field(default_factory=list)
    url: Optional[str] = None


class Commit(BaseModel):
    """Git commit model."""
    sha: str
    repo_id: int
    message: str
    author: Author  # Changed from str to Author (includes name, email, etc.)
    date: datetime
    url: Optional[str] = None
    pr_number: Optional[int] = None


class Ticket(BaseModel):
    """Issue/ticket model."""
    id: Optional[int] = None
    repo_id: int
    number: int
    key: str  # e.g., "JIRA-123" or issue number
    title: str
    body: Optional[str] = None
    state: str
    labels: List[Label] = Field(default_factory=list)
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    category: Optional[str] = None
    tags: Dict[str, str] = Field(default_factory=dict)


class Release(BaseModel):
    """Release model."""
    id: Optional[int] = None
    repo_id: int
    version: str
    tag_name: str
    name: Optional[str] = None
    body: Optional[str] = None
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    is_draft: bool = False
    is_prerelease: bool = False
    url: Optional[str] = None
    target_commitish: Optional[str] = None


class ReleaseNote(BaseModel):
    """Release note entry model."""
    ticket_key: Optional[str] = None
    title: str
    description: Optional[str] = None
    migration_notes: Optional[str] = None
    category: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    authors: List[Author] = Field(default_factory=list)  # Changed from List[str] to List[Author]
    pr_numbers: List[int] = Field(default_factory=list)
    commit_shas: List[str] = Field(default_factory=list)
    ticket_url: Optional[str] = None  # URL to the ticket/issue
    pr_url: Optional[str] = None  # URL to the pull request
    url: Optional[str] = None  # Smart URL: ticket_url if available, else pr_url
    short_link: Optional[str] = None  # Short format: #1234
    short_repo_link: Optional[str] = None  # Short format with repo: owner/repo#1234
    tags: Dict[str, str] = Field(default_factory=dict)


class ConsolidatedChange(BaseModel):
    """Consolidated change from commits/PRs."""
    type: str  # "ticket", "pr", "commit"
    ticket_key: Optional[str] = None
    pr_number: Optional[int] = None
    commits: List[Commit] = Field(default_factory=list)
    prs: List[PullRequest] = Field(default_factory=list)
    ticket: Optional[Ticket] = None
    release_note: Optional[ReleaseNote] = None
