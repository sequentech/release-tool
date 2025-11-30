"""Configuration management for the release tool."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Literal
from enum import Enum
from pydantic import BaseModel, Field, model_validator
import tomli
import tomlkit


class PolicyAction(str, Enum):
    """Policy action types."""
    IGNORE = "ignore"
    WARN = "warn"
    ERROR = "error"


class TicketExtractionStrategy(str, Enum):
    """Ticket extraction strategies."""
    BRANCH_NAME = "branch_name"
    COMMIT_MESSAGE = "commit_message"
    PR_BODY = "pr_body"
    PR_TITLE = "pr_title"


class TicketPattern(BaseModel):
    """A ticket extraction pattern with its associated strategy."""
    order: int
    strategy: TicketExtractionStrategy
    pattern: str
    description: Optional[str] = None


class CategoryConfig(BaseModel):
    """Category configuration."""
    name: str
    labels: List[str]
    order: int = 0
    alias: Optional[str] = None  # Short alias for template references

    def matches_label(self, label: str, source: str) -> bool:
        """
        Check if a label matches this category.

        Args:
            label: The label name to check
            source: Either "pr" or "ticket" indicating where the label comes from

        Returns:
            True if the label matches this category
        """
        for pattern in self.labels:
            # Check for prefix (pr:, ticket:, or no prefix for any)
            if pattern.startswith("pr:"):
                # Only match PR labels
                if source == "pr" and pattern[3:] == label:
                    return True
            elif pattern.startswith("ticket:"):
                # Only match ticket labels
                if source == "ticket" and pattern[7:] == label:
                    return True
            else:
                # No prefix = match from any source
                if pattern == label:
                    return True
        return False


class PRTemplateConfig(BaseModel):
    """Pull request template configuration for release notes."""
    branch_template: str = Field(
        default="docs/{{issue_repo}}-{{issue_number}}/{{target_branch}}",
        description="Branch name template for release notes PR (Jinja2 syntax)"
    )
    title_template: str = Field(
        default="Release notes for {{version}}",
        description="PR title template (Jinja2 syntax)"
    )
    body_template: str = Field(
        default="Parent issue: {{issue_link}}\n\n"
                "Automated release notes for version {{version}}.\n\n"
                "## Summary\n"
                "This PR adds release notes for {{version}} with {{num_changes}} changes across {{num_categories}} categories.",
        description="PR body template (Jinja2 syntax)"
    )


class TicketTemplateConfig(BaseModel):
    """Ticket template configuration for release tracking."""
    title_template: str = Field(
        default="✨ Prepare Release {{version}}",
        description="Ticket title template (Jinja2 syntax). Available variables: {{version}}, {{major}}, {{minor}}, {{patch}}"
    )
    body_template: str = Field(
        default=(
            "### DevOps Tasks\n\n"
            "- [ ] Github release notes: correct and complete\n"
            "- [ ] Docusaurus release notes: correct and complete\n"
            "- [ ] BEYOND-PR-HERE for a new default tenant/election-event template and any new other changes (branch should be `release/{{major}}.{{minor}}`)\n"
            "- [ ] GITOPS-PR-HERE for a new default tenant/election-event template and any new other changes (branch should be `release/{{major}}.{{minor}}`)\n"
            "- [ ] Request in [Environment spreadsheet](https://docs.google.com/spreadsheets/d/1TDxb8r9dZKwNxHc3lAL0mtFDSsoou985NX_Y44eA7V4/edit#gid=0) to get deployment approval by environment owners\n\n"
            "NOTE: Please also update deployment status when a release is deployed in an environment.\n\n"
            "### QA Flight List\n\n"
            "- [ ] Deploy in `dev`\n"
            "- [ ] Positive Test in `dev`\n"
            "- [ ] Deploy in `qa`\n"
            "- [ ] Positive Test in `qa`\n\n"
            "### PRs to deploy new version in different environments\n\n"
            "- [ ] PR 1"
        ),
        description="Ticket body template (Jinja2 syntax). Available variables: {{version}}, {{major}}, {{minor}}, {{patch}}, "
                    "{{num_changes}}, {{num_categories}}"
    )
    labels: List[str] = Field(
        default_factory=lambda: ["release", "devops", "infrastructure"],
        description="Labels to apply to the release tracking ticket"
    )
    assignee: Optional[str] = Field(
        default=None,
        description="GitHub username to assign the ticket to. If None, assigns to the authenticated user from the GitHub token."
    )
    project_id: Optional[str] = Field(
        default=None,
        description="GitHub Project ID (number) to add the ticket to. Find this in the project URL: github.com/orgs/ORG/projects/ID"
    )
    project_status: Optional[str] = Field(
        default=None,
        description="Status to set in the GitHub Project (e.g., 'Todo', 'In Progress', 'Done')"
    )
    project_fields: Dict[str, str] = Field(
        default_factory=dict,
        description="Custom fields to set in the GitHub Project. Maps field name to field value. "
                    "Example: {'Priority': 'High', 'Sprint': '2024-Q1'}"
    )
    type: Optional[str] = Field(
        default=None,
        description="Issue type to set (e.g., 'Task', 'Bug'). This is often mapped to a label or a specific field."
    )
    milestone: Optional[str] = Field(
        default=None,
        description="Milestone name to assign the ticket to (e.g., 'v1.0.0')."
    )


class TicketPolicyConfig(BaseModel):
    """Ticket extraction and consolidation policy configuration."""
    patterns: List[TicketPattern] = Field(
        default_factory=lambda: [
            TicketPattern(
                order=1,
                strategy=TicketExtractionStrategy.BRANCH_NAME,
                pattern=r'/(?P<repo>\w+)-(?P<ticket>\d+)',
                description="Branch names like feat/meta-123/main"
            ),
            TicketPattern(
                order=2,
                strategy=TicketExtractionStrategy.PR_BODY,
                pattern=r'Parent issue:.*?/issues/(?P<ticket>\d+)',
                description="Parent issue URL in PR body"
            ),
            TicketPattern(
                order=3,
                strategy=TicketExtractionStrategy.PR_TITLE,
                pattern=r'#(?P<ticket>\d+)',
                description="GitHub issue reference in PR title"
            ),
            TicketPattern(
                order=4,
                strategy=TicketExtractionStrategy.COMMIT_MESSAGE,
                pattern=r'#(?P<ticket>\d+)',
                description="GitHub issue reference in commit message"
            ),
            TicketPattern(
                order=5,
                strategy=TicketExtractionStrategy.COMMIT_MESSAGE,
                pattern=r'(?P<project>[A-Z]+)-(?P<ticket>\d+)',
                description="JIRA-style tickets in commit message"
            ),
        ],
        description="Ordered list of patterns with their extraction strategies"
    )
    no_ticket_action: PolicyAction = Field(
        default=PolicyAction.WARN,
        description="What to do when no ticket is found"
    )
    unclosed_ticket_action: PolicyAction = Field(
        default=PolicyAction.WARN,
        description="What to do with unclosed tickets"
    )
    partial_ticket_action: PolicyAction = Field(
        default=PolicyAction.WARN,
        description="What to do with partial ticket matches (extracted but not found or wrong repo)"
    )
    inter_release_duplicate_action: PolicyAction = Field(
        default=PolicyAction.WARN,
        description="What to do when a ticket appears in multiple releases (ignore=exclude from new release, warn=include but warn, error=fail)"
    )
    consolidation_enabled: bool = Field(
        default=True,
        description="Whether to consolidate commits by parent ticket"
    )
    description_section_regex: Optional[str] = Field(
        default=r'(?:## Description|## Summary)\n(.*?)(?=\n##|\Z)',
        description="Regex to extract description from ticket body"
    )
    migration_section_regex: Optional[str] = Field(
        default=r'(?:## Migration|## Migration Notes)\n(.*?)(?=\n##|\Z)',
        description="Regex to extract migration notes from ticket body"
    )


class VersionPolicyConfig(BaseModel):
    """Version comparison and gap policy configuration."""
    gap_detection: PolicyAction = Field(
        default=PolicyAction.WARN,
        description="What to do when version gaps are detected"
    )
    tag_prefix: str = Field(
        default="v",
        description="Prefix for version tags"
    )


class BranchPolicyConfig(BaseModel):
    """Branch management policy for releases."""
    release_branch_template: str = Field(
        default="release/{major}.{minor}",
        description="Template for release branch names. Use {major}, {minor}, {patch} placeholders"
    )
    default_branch: str = Field(
        default="main",
        description="Default branch for new major versions"
    )
    create_branches: bool = Field(
        default=True,
        description="Automatically create release branches if they don't exist"
    )
    branch_from_previous_release: bool = Field(
        default=True,
        description="Branch new minor versions from previous release branch (if it exists)"
    )


class ReleaseNoteConfig(BaseModel):
    """Release note generation configuration."""
    categories: List[CategoryConfig] = Field(
        default_factory=lambda: [
            CategoryConfig(
                name="💥 Breaking Changes",
                labels=["breaking-change", "breaking"],
                order=1,
                alias="breaking"
            ),
            CategoryConfig(
                name="🚀 Features",
                labels=["feature", "enhancement", "feat"],
                order=2,
                alias="features"
            ),
            CategoryConfig(
                name="🛠 Bug Fixes",
                labels=["bug", "fix", "bugfix", "hotfix"],
                order=3,
                alias="bugfixes"
            ),
            CategoryConfig(
                name="📖 Documentation",
                labels=["docs", "documentation"],
                order=4,
                alias="docs"
            ),
            CategoryConfig(
                name="🛡 Security Updates",
                labels=["security"],
                order=5,
                alias="security"
            ),
            CategoryConfig(
                name="Other Changes",
                labels=[],
                order=99,
                alias="other"
            )
        ],
        description="Categories for grouping release notes"
    )
    excluded_labels: List[str] = Field(
        default_factory=lambda: ["skip-changelog", "internal", "wip", "do-not-merge"],
        description="Labels that exclude items from release notes"
    )
    title_template: str = Field(
        default="Release {{ version }}",
        description="Jinja2 template for release title"
    )
    description_template: str = Field(
        default="",
        description="Jinja2 template for release description (deprecated - use output_template)"
    )
    entry_template: str = Field(
        default=(
            "- {{ title }}\n"
            "  {% if short_repo_link %}{{ short_repo_link }}{% endif %}\n"
            "  {% if authors %}\n"
            "  by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}\n"
            "  {% endif %}"
        ),
        description="Jinja2 template for each release note entry (used as sub-template in output_template)"
    )
    release_output_template: Optional[str] = Field(
        default=(
            "{% set breaking_with_desc = all_notes|selectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}\n"
            "{% if breaking_with_desc|length > 0 %}\n"
            "## 💥 Breaking Changes\n"
            "\n"
            "{% for note in breaking_with_desc %}\n"
            "### {{ note.title }}\n"
            "\n"
            "{{ note.description }}\n"
            "\n"
            "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
            "\n"
            "{% endfor %}\n"
            "{% endif %}\n"
            "\n"
            "{% set migration_notes = all_notes|selectattr('migration_notes')|list %}\n"
            "{% if migration_notes|length > 0 %}\n"
            "## 🔄 Migrations\n"
            "\n"
            "{% for note in migration_notes %}\n"
            "### {{ note.title }}\n"
            "\n"
            "{{ note.migration_notes }}\n"
            "\n"
            "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
            "\n"
            "{% endfor %}\n"
            "{% endif %}\n"
            "\n"
            "{% set non_breaking_with_desc = all_notes|rejectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}\n"
            "{% if non_breaking_with_desc|length > 0 %}\n"
            "## 📝 Highlights\n"
            "\n"
            "{% for note in non_breaking_with_desc %}\n"
            "### {{ note.title }}\n"
            "\n"
            "{{ note.description }}\n"
            "\n"
            "{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}\n"
            "\n"
            "{% endfor %}\n"
            "{% endif %}\n"
            "\n"
            "## 📋 All Changes\n"
            "\n"
            "{% for category in categories %}\n"
            "### {{ category.name }}\n"
            "\n"
            "{% for note in category.notes %}\n"
            "{{ render_entry(note) }}\n"
            "\n"
            "{% endfor %}\n"
            "{% endfor %}"
        ),
        description="Master Jinja2 template for GitHub release notes output. "
                    "Available variables: version, title, categories (with 'alias' field), "
                    "all_notes, render_entry (function to render entry_template). "
                    "Note variables: title, url (prioritizes ticket_url over pr_url), ticket_url, pr_url, "
                    "short_link (#1234), short_repo_link (owner/repo#1234), pr_numbers, authors, description, etc."
    )
    doc_output_template: Optional[str] = Field(
        default=None,
        description="Jinja2 template for Docusaurus/documentation release notes output. "
                    "Wraps the GitHub release notes with documentation-specific formatting (e.g., frontmatter). "
                    "Available variables: version, title, categories, all_notes, render_entry, "
                    "render_release_notes (function to render release_output_template). "
                    "Example: '---\\nid: release-{{version}}\\ntitle: {{title}}\\n---\\n{{ render_release_notes() }}'"
    )


class SyncConfig(BaseModel):
    """Sync configuration for GitHub data fetching."""
    cutoff_date: Optional[str] = Field(
        default=None,
        description="ISO format date (YYYY-MM-DD) to limit historical fetching. Only fetch tickets/PRs from this date onwards."
    )
    parallel_workers: int = Field(
        default=20,
        description="Number of parallel workers for GitHub API calls"
    )
    clone_code_repo: bool = Field(
        default=True,
        description="Whether to clone/sync the code repository locally for offline operation"
    )
    code_repo_path: Optional[str] = Field(
        default=None,
        description="Local path to clone code repository. Defaults to .release_tool_cache/{repo_name}"
    )
    show_progress: bool = Field(
        default=True,
        description="Show progress updates during sync (e.g., 'syncing 13 / 156 tickets')"
    )


class RepositoryConfig(BaseModel):
    """Repository configuration."""
    code_repo: str = Field(
        description="Full name of code repository (owner/name)"
    )
    ticket_repos: List[str] = Field(
        default_factory=list,
        description="List of ticket repository names (owner/name). If empty, uses code_repo."
    )
    default_branch: Optional[str] = Field(
        default=None,
        description="Default branch name (deprecated: use branch_policy.default_branch instead)"
    )


class GitHubConfig(BaseModel):
    """GitHub configuration."""
    token: Optional[str] = Field(
        default=None,
        description="GitHub API token (can also use GITHUB_TOKEN env var)"
    )
    api_url: str = Field(
        default="https://api.github.com",
        description="GitHub API URL"
    )


class DatabaseConfig(BaseModel):
    """Database configuration."""
    path: str = Field(
        default="release_tool.db",
        description="Path to SQLite database file"
    )


class OutputConfig(BaseModel):
    """Output configuration for release notes."""
    release_output_path: str = Field(
        default="docs/releases/{version}.md",
        description="File path template for GitHub release notes (supports {version}, {major}, {minor}, {patch})"
    )
    doc_output_path: Optional[str] = Field(
        default=None,
        description="File path template for Docusaurus/documentation release notes (supports {version}, {major}, {minor}, {patch}). "
                    "If set, doc_output_template must also be configured."
    )
    draft_output_path: str = Field(
        default=".release_tool_cache/draft-releases/{{code_repo}}/{{version}}.md",
        description="File path template for draft release notes (supports {{code_repo}}, {{version}}, {{major}}, {{minor}}, {{patch}})"
    )
    assets_path: str = Field(
        default="docs/releases/assets/{version}",
        description="Path template for downloaded media assets (images, videos)"
    )
    download_media: bool = Field(
        default=True,
        description="Download and include images/videos from ticket descriptions"
    )
    create_github_release: bool = Field(
        default=False,
        description="Whether to create a GitHub release"
    )
    create_pr: bool = Field(
        default=False,
        description="Whether to create a PR with release notes"
    )
    release_mode: Literal["draft", "published"] = Field(
        default="draft",
        description="Default release mode: 'draft' or 'published'"
    )
    prerelease: Union[bool, Literal["auto"]] = Field(
        default="auto",
        description="Mark GitHub releases as prereleases. Options: 'auto' (detect from version), true, false"
    )
    create_ticket: bool = Field(
        default=True,
        description="Whether to create a tracking issue for the release. "
                    "When true, a GitHub issue will be created and PR templates can use {{issue_repo}}, {{issue_number}}, and {{issue_link}} variables."
    )
    ticket_templates: TicketTemplateConfig = Field(
        default_factory=TicketTemplateConfig,
        description="Templates for release tracking ticket (title, body, labels)"
    )
    pr_templates: PRTemplateConfig = Field(
        default_factory=PRTemplateConfig,
        description="Templates for PR branch, title, and body"
    )


class Config(BaseModel):
    """Main configuration model."""
    config_version: str = Field(default="1.1", description="Config file format version")
    repository: RepositoryConfig
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    ticket_policy: TicketPolicyConfig = Field(default_factory=TicketPolicyConfig)
    version_policy: VersionPolicyConfig = Field(default_factory=VersionPolicyConfig)
    branch_policy: BranchPolicyConfig = Field(default_factory=BranchPolicyConfig)
    release_notes: ReleaseNoteConfig = Field(default_factory=ReleaseNoteConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode='after')
    def validate_doc_output(self):
        """Validate that doc_output_path requires doc_output_template."""
        if self.output.doc_output_path and not self.release_notes.doc_output_template:
            raise ValueError(
                "doc_output_path is configured but doc_output_template is not set. "
                "Both must be configured together for Docusaurus output."
            )
        return self

    @classmethod
    def from_file(cls, config_path: str, auto_upgrade: bool = False) -> "Config":
        """Load configuration from TOML file.

        Args:
            config_path: Path to the config file
            auto_upgrade: If True, automatically upgrade old configs without prompting

        Returns:
            Config object
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, 'rb') as f:
            data = tomli.load(f)

        # Check and upgrade config version if needed
        from .migrations import MigrationManager
        manager = MigrationManager()
        current_version = data.get('config_version', '1.0')

        if manager.needs_upgrade(current_version):
            # Config is out of date
            target_version = manager.CURRENT_VERSION
            changes = manager.get_changes_description(current_version, target_version)

            if auto_upgrade:
                # Auto-upgrade without prompting
                print(f"Auto-upgrading config from v{current_version} to v{target_version}...")
                data = manager.upgrade_config(data, target_version)

                # Save upgraded config back to file
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(tomlkit.dumps(data))
                print(f"Config upgraded and saved to {config_path}")
            else:
                # Prompt user to upgrade
                print(f"\n⚠️  Config file is version {current_version}, but current version is {target_version}")
                print(f"\nChanges in v{target_version}:")
                print(changes)
                print(f"\nYou need to upgrade your config file to continue.")

                response = input("\nUpgrade now? [Y/n]: ").strip().lower()
                if response in ['', 'y', 'yes']:
                    data = manager.upgrade_config(data, target_version)

                    # Save upgraded config back to file
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(tomlkit.dumps(data))
                    print(f"✓ Config upgraded to v{target_version} and saved to {config_path}")
                else:
                    raise ValueError(
                        f"Config version {current_version} is not supported. "
                        f"Please upgrade to v{target_version} using: release-tool update-config"
                    )

        # Override GitHub token from environment if present
        if 'github' not in data:
            data['github'] = {}
        if not data['github'].get('token'):
            data['github']['token'] = os.getenv('GITHUB_TOKEN')

        return cls(**data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Load configuration from dictionary."""
        # Override GitHub token from environment if present
        if 'github' not in data:
            data['github'] = {}
        if not data['github'].get('token'):
            data['github']['token'] = os.getenv('GITHUB_TOKEN')

        return cls(**data)

    def get_ticket_repos(self) -> List[str]:
        """Get the list of ticket repositories (defaults to code repo if not specified)."""
        if self.repository.ticket_repos:
            return self.repository.ticket_repos
        return [self.repository.code_repo]

    def get_code_repo_path(self) -> str:
        """Get the local path for the cloned code repository."""
        if self.sync.code_repo_path:
            return self.sync.code_repo_path
        # Default to .release_tool_cache/{repo_name}
        repo_name = self.repository.code_repo.split('/')[-1]
        return str(Path.cwd() / '.release_tool_cache' / repo_name)

    def get_category_map(self) -> Dict[str, List[str]]:
        """Get a mapping of category names to their labels."""
        return {cat.name: cat.labels for cat in self.release_notes.categories}

    def get_ordered_categories(self) -> List[str]:
        """Get category names in order."""
        sorted_cats = sorted(self.release_notes.categories, key=lambda c: c.order)
        return [cat.name for cat in sorted_cats]


def load_config(config_path: Optional[str] = None, auto_upgrade: bool = False) -> Config:
    """Load configuration from file or use defaults.

    Args:
        config_path: Path to config file (optional, will search default locations if not provided)
        auto_upgrade: If True, automatically upgrade old configs without prompting

    Returns:
        Config object
    """
    if config_path and Path(config_path).exists():
        return Config.from_file(config_path, auto_upgrade=auto_upgrade)

    # Look for default config files
    default_paths = [
        "release_tool.toml",
        ".release_tool.toml",
        "config/release_tool.toml"
    ]

    for default_path in default_paths:
        if Path(default_path).exists():
            return Config.from_file(default_path, auto_upgrade=auto_upgrade)

    # Return minimal config if no file found (will fail validation if required fields missing)
    raise FileNotFoundError(
        "No configuration file found. Please create release_tool.toml with required settings."
    )
