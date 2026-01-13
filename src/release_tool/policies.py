# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Policy implementations for issue extraction, consolidation, and release notes."""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from enum import Enum
from rich.console import Console

from .models import (
    Commit, PullRequest, Issue, ReleaseNote, ConsolidatedChange, Label, SemanticVersion
)
from .config import (
    Config, PolicyAction, IssueExtractionStrategy
)

console = Console()


class PartialIssueReason(Enum):
    """Reasons why a issue might be partially matched."""

    # Not found reasons
    OLDER_THAN_CUTOFF = "older_than_cutoff"  # Issue may be older than pull cutoff date
    TYPO = "typo"  # Issue may not exist (typo in branch/PR)
    PULL_NOT_RUN = "pull_not_run"  # Pull may not have been run yet

    # Different repo reasons
    REPO_CONFIG_MISMATCH = "repo_config_mismatch"  # Issue found in different repo than configured
    WRONG_ISSUE_REPOS = "wrong_issue_repos"  # Mismatch between issue_repos config and actual location

    @property
    def description(self) -> str:
        """Get human-readable description of the reason."""
        descriptions = {
            PartialIssueReason.OLDER_THAN_CUTOFF: "Issue may be older than pull cutoff date",
            PartialIssueReason.TYPO: "Issue may not exist (typo in branch/PR)",
            PartialIssueReason.PULL_NOT_RUN: "Pull may not have been run yet",
            PartialIssueReason.REPO_CONFIG_MISMATCH: "Issue found in different repo than configured",
            PartialIssueReason.WRONG_ISSUE_REPOS: "Check repository.issue_repos in config",
        }
        return descriptions.get(self, self.value)


@dataclass
class PartialIssueMatch:
    """
    Information about a partial issue match.

    A partial match occurs when a issue is extracted from a branch/PR/commit
    but cannot be fully resolved to a issue in the database, or is found
    in an unexpected repository.
    """
    issue_key: str  # The extracted issue key (e.g., "8624", "#123")
    extracted_from: str  # Human-readable description of source (e.g., "branch feat/meta-8624/main, pattern #1")
    match_type: str  # "not_found" or "different_repo"
    found_in_repo: Optional[str] = None  # For different_repo type: which repo it was found in
    issue_url: Optional[str] = None  # For different_repo type: URL to the issue
    potential_reasons: Set[PartialIssueReason] = field(default_factory=set)  # Set of potential causes


class IssueExtractor:
    """Extract issue references from various sources."""

    def __init__(self, config: Config, debug: bool = False):
        self.config = config
        self.debug = debug
        # Sort patterns by order field, then group by strategy for efficient lookup
        sorted_patterns = sorted(config.issue_policy.patterns, key=lambda p: p.order)
        self.pattern_configs = sorted_patterns  # Store for debug output
        self.patterns_by_strategy: Dict[IssueExtractionStrategy, List[re.Pattern]] = {}
        for issue_pattern in sorted_patterns:
            strategy = issue_pattern.strategy
            if strategy not in self.patterns_by_strategy:
                self.patterns_by_strategy[strategy] = []
            self.patterns_by_strategy[strategy].append(re.compile(issue_pattern.pattern))

    def _extract_with_patterns(self, text: str, patterns: List[re.Pattern], show_results: bool = False) -> List[str]:
        """Extract issue references using a list of patterns."""
        issues = []
        for i, pattern in enumerate(patterns):
            matches_found = []
            # Use finditer to get match objects and extract named groups
            for match in pattern.finditer(text):
                # Try to extract the 'issue' named group
                try:
                    issue = match.group('issue')
                    issues.append(issue)
                    matches_found.append(issue)
                except IndexError:
                    # If no 'issue' group, fall back to the entire match or first group
                    if match.groups():
                        issue = match.group(1)
                        issues.append(issue)
                        matches_found.append(issue)
                    else:
                        issue = match.group(0)
                        issues.append(issue)
                        matches_found.append(issue)

            if self.debug and show_results:
                if matches_found:
                    console.print(f"    [green]✅ MATCH! Extracted: {matches_found}[/green]")
                else:
                    console.print(f"    [dim]❌ No match[/dim]")

        return issues

    def extract_from_commit(self, commit: Commit) -> List[str]:
        """Extract issue references from commit message."""
        if self.debug:
            console.print(f"\n🔍 [bold cyan]Extracting from commit:[/bold cyan] {commit.sha[:7]} - {commit.message[:60]}{'...' if len(commit.message) > 60 else ''}")

        patterns = self.patterns_by_strategy.get(IssueExtractionStrategy.COMMIT_MESSAGE, [])

        # Debug: show which patterns apply to commit_message
        if self.debug and patterns:
            matching_configs = [p for p in self.pattern_configs if p.strategy == IssueExtractionStrategy.COMMIT_MESSAGE]
            for pattern_config in matching_configs:
                console.print(f"  [dim]Trying pattern #{pattern_config.order} (strategy={pattern_config.strategy.value})[/dim]")
                if pattern_config.description:
                    console.print(f"    Description: \"{pattern_config.description}\"")
                console.print(f"    Regex: {pattern_config.pattern}")
                console.print(f"    Text: \"{commit.message[:100]}{'...' if len(commit.message) > 100 else ''}\"")

        issues = list(set(self._extract_with_patterns(commit.message, patterns, show_results=self.debug)))

        if self.debug:
            if issues:
                console.print(f"  [green]✅ Extracted issues: {issues}[/green]")
            else:
                console.print(f"  [yellow]- Extracted issues: (none)[/yellow]")

        return issues

    def extract_from_pr(self, pr: PullRequest) -> List[str]:
        """Extract issue references from PR using configured strategies."""
        if self.debug:
            console.print(f"\n🔍 [bold cyan]Extracting from PR #{pr.number}:[/bold cyan] {pr.title[:60]}{'...' if len(pr.title) > 60 else ''}")

        issues = []

        # Try patterns in order (sorted by order field)
        sorted_patterns = sorted(self.config.issue_policy.patterns, key=lambda p: p.order)
        for issue_pattern in sorted_patterns:
            strategy = issue_pattern.strategy
            text = None
            source_name = None

            if strategy == IssueExtractionStrategy.PR_BODY and pr.body:
                text = pr.body
                source_name = "pr_body"
            elif strategy == IssueExtractionStrategy.PR_TITLE and pr.title:
                text = pr.title
                source_name = "pr_title"
            elif strategy == IssueExtractionStrategy.BRANCH_NAME and pr.head_branch:
                text = pr.head_branch
                source_name = "branch_name"

            if self.debug:
                console.print(f"  [dim]Pattern #{issue_pattern.order} (strategy={strategy.value})[/dim]")
                if issue_pattern.description:
                    console.print(f"    Description: \"{issue_pattern.description}\"")
                console.print(f"    Regex: {issue_pattern.pattern}")

            if text:
                if self.debug:
                    console.print(f"    Source: {source_name}")
                    console.print(f"    Text: \"{text[:100]}{'...' if len(text) > 100 else ''}\"")

                pattern = re.compile(issue_pattern.pattern)
                extracted = self._extract_with_patterns(text, [pattern], show_results=self.debug)
                if extracted:
                    issues.extend(extracted)
                    if self.debug:
                        console.print(f"    [yellow]🛑 Stopping (first match wins)[/yellow]")
                    # Stop on first match to respect priority order
                    break
            else:
                if self.debug:
                    console.print(f"    [dim]❌ Skipped (no {strategy.value} available)[/dim]")

        if self.debug:
            if issues:
                console.print(f"  [green]✅ Extracted issues: {list(set(issues))}[/green]")
            else:
                console.print(f"  [yellow]- Extracted issues: (none)[/yellow]")

        return list(set(issues))

    def extract_from_branch(self, branch_name: str) -> List[str]:
        """Extract issue references from branch name."""
        if self.debug:
            console.print(f"\n🔍 [bold cyan]Extracting from branch:[/bold cyan] {branch_name}")

        patterns = self.patterns_by_strategy.get(IssueExtractionStrategy.BRANCH_NAME, [])

        # Debug: show which patterns apply to branch_name
        if self.debug and patterns:
            matching_configs = [p for p in self.pattern_configs if p.strategy == IssueExtractionStrategy.BRANCH_NAME]
            for pattern_config in matching_configs:
                console.print(f"  [dim]Trying pattern #{pattern_config.order} (strategy={pattern_config.strategy.value})[/dim]")
                if pattern_config.description:
                    console.print(f"    Description: \"{pattern_config.description}\"")
                console.print(f"    Regex: {pattern_config.pattern}")
                console.print(f"    Text: \"{branch_name}\"")

        issues = list(set(self._extract_with_patterns(branch_name, patterns, show_results=self.debug)))

        if self.debug:
            if issues:
                console.print(f"  [green]✅ Extracted issues: {issues}[/green]")
            else:
                console.print(f"  [yellow]- Extracted issues: (none)[/yellow]")

        return issues


class CommitConsolidator:
    """Consolidate commits by parent issue."""

    def __init__(self, config: Config, extractor: IssueExtractor, debug: bool = False):
        self.config = config
        self.extractor = extractor
        self.debug = debug

    def consolidate(
        self,
        commits: List[Commit],
        prs: Dict[int, PullRequest]
    ) -> List[ConsolidatedChange]:
        """
        Consolidate commits by their parent issue.

        Returns a list of ConsolidatedChange objects, grouped by issue.
        """
        if not self.config.issue_policy.consolidation_enabled:
            # Return each commit as a separate change
            return [
                ConsolidatedChange(
                    type="commit",
                    commits=[commit]
                )
                for commit in commits
            ]

        consolidated: Dict[str, ConsolidatedChange] = {}

        if self.debug:
            console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
            console.print(f"[bold magenta]📦 CONSOLIDATION PHASE[/bold magenta]")
            console.print(f"[bold magenta]{'='*60}[/bold magenta]\n")

        for commit in commits:
            if self.debug:
                console.print(f"\n📦 [bold]Consolidating commit {commit.sha[:7]}:[/bold] \"{commit.message[:60]}{'...' if len(commit.message) > 60 else ''}\"")

            # Try to find issue from commit
            issues = self.extractor.extract_from_commit(commit)

            if self.debug:
                console.print(f"  → Issues from commit: {issues if issues else '(none)'}")

            # Try to find associated PR
            pr = prs.get(commit.pr_number) if commit.pr_number else None
            if pr:
                if self.debug:
                    console.print(f"  ✅ Associated PR: #{pr.number} \"{pr.title[:50]}{'...' if len(pr.title) > 50 else ''}\"")
                pr_issues = self.extractor.extract_from_pr(pr)
                if self.debug:
                    console.print(f"  {'✅' if pr_issues else '→'} Issues from PR: {pr_issues if pr_issues else '(none)'}")
                issues.extend(pr_issues)
            elif self.debug:
                console.print(f"  → Associated PR: (none)")

            issues = list(set(issues))  # Remove duplicates

            if issues:
                # Use first issue as the parent
                issue_key = issues[0]
                if self.debug:
                    console.print(f"  [green]✅ Consolidated under issue: {issue_key}[/green]")

                if issue_key not in consolidated:
                    consolidated[issue_key] = ConsolidatedChange(
                        type="issue",
                        issue_key=issue_key,
                        commits=[],
                        prs=[]
                    )
                consolidated[issue_key].commits.append(commit)
                if pr and pr not in consolidated[issue_key].prs:
                    consolidated[issue_key].prs.append(pr)
            elif pr:
                # No issue but has PR
                pr_key = f"pr-{pr.number}"
                if self.debug:
                    console.print(f"  [yellow]✅ Consolidated under PR: #{pr.number}[/yellow]")

                if pr_key not in consolidated:
                    consolidated[pr_key] = ConsolidatedChange(
                        type="pr",
                        pr_number=pr.number,
                        commits=[],
                        prs=[pr]
                    )
                consolidated[pr_key].commits.append(commit)
            else:
                # No issue and no PR - standalone commit
                commit_key = f"commit-{commit.sha[:8]}"
                if self.debug:
                    console.print(f"  [dim]- Standalone commit (no issue or PR)[/dim]")

                consolidated[commit_key] = ConsolidatedChange(
                    type="commit",
                    commits=[commit]
                )

        return list(consolidated.values())

    def handle_missing_issues(
        self,
        consolidated_changes: List[ConsolidatedChange]
    ):
        """Handle changes that don't have a parent issue."""
        action = self.config.issue_policy.no_issue_action
        no_issue_changes = [
            c for c in consolidated_changes
            if c.type in ["commit", "pr"] or not c.issue_key
        ]

        if not no_issue_changes:
            return

        if action == PolicyAction.ERROR:
            raise ValueError(
                f"Found {len(no_issue_changes)} changes without a parent issue. "
                "Configure no_issue_action policy to allow this."
            )
        elif action == PolicyAction.WARN:
            console.print(
                f"[yellow]WARNING: Found {len(no_issue_changes)} changes without a parent issue[/yellow]"
            )
            for change in no_issue_changes[:5]:  # Show first 5
                if change.commits:
                    msg = change.commits[0].message.split('\n')[0]
                    console.print(f"  - {msg[:80]}")


class ReleaseNoteGenerator:
    """Generate release notes from consolidated changes."""

    # NOTE: release_output_template is now configured via config.release_notes.release_output_template
    # This constant is kept for reference but is no longer used

    def __init__(self, config: Config):
        self.config = config

    def _get_fallback_category_name(self) -> str:
        """
        Get the fallback category name by finding the category with alias='other'.

        This allows users to name the fallback category whatever they want (e.g., "Other",
        "Miscellaneous", "Other Changes") as long as they set alias="other".

        Returns:
            The name of the category with alias='other', or "Other" as hardcoded fallback
            if no category has that alias.
        """
        for category in self.config.release_notes.categories:
            if category.alias == "other":
                return category.name
        # Fallback to hardcoded "Other" if no category with alias='other' found
        return "Other"

    def create_release_note(
        self,
        change: ConsolidatedChange,
        issue: Optional[Issue] = None
    ) -> ReleaseNote:
        """Create a release note from a consolidated change."""
        # Extract and deduplicate authors from commits and PRs
        authors = self._deduplicate_authors(change)
        
        pr_numbers = list(set(pr.number for pr in change.prs))
        commit_shas = [commit.sha for commit in change.commits]

        # Determine title
        if issue:
            title = issue.title
        elif change.prs:
            title = change.prs[0].title
        elif change.commits:
            title = change.commits[0].message.split('\n')[0]
        else:
            title = "Unknown change"

        # Determine category from labels
        category = self._determine_category(change, issue)

        # Extract description and migration notes if we have a issue
        description = None
        migration_notes = None
        if issue and issue.body:
            description = self._extract_section(
                issue.body,
                self.config.issue_policy.description_section_regex
            )
            migration_notes = self._extract_section(
                issue.body,
                self.config.issue_policy.migration_section_regex
            )

        # Get URLs
        issue_url = None
        pr_url = None
        url = None  # Smart URL: issue_url if available, else pr_url

        if issue:
            issue_url = issue.url
            url = issue_url  # Prefer issue URL

        if change.prs:
            pr_url = change.prs[0].url
            if not url:  # Use PR URL if no issue URL
                url = pr_url

        # Compute short links from the smart URL
        short_link = None
        short_repo_link = None
        if url:
            repo_name, number = self._extract_github_url_info(url)
            if number:
                short_link = f"#{number}"
                if repo_name:
                    short_repo_link = f"{repo_name}#{number}"

        # Get labels
        labels = []
        if issue:
            labels = [label.name for label in issue.labels]
        elif change.prs:
            labels = [label.name for pr in change.prs for label in pr.labels]

        return ReleaseNote(
            issue_key=change.issue_key,
            title=title,
            description=description,
            migration_notes=migration_notes,
            category=category,
            labels=labels,
            authors=authors,
            pr_numbers=pr_numbers,
            commit_shas=commit_shas,
            issue_url=issue_url,
            pr_url=pr_url,
            url=url,
            short_link=short_link,
            short_repo_link=short_repo_link
        )

    def _deduplicate_authors(self, change: ConsolidatedChange) -> List[Any]:
        """
        Deduplicate authors from commits and PRs.
        
        Prioritizes PR authors because they have GitHub usernames (needed for @mentions).
        Commits often only have Name/Email, and Email might be private/missing in PR data.
        """
        final_authors_map = {}  # Key by identifier -> Author

        # 1. Index PR authors (they are our "source of truth" for GitHub identity)
        pr_authors_by_pr_number = {}
        known_authors_by_name = {}
        known_authors_by_email = {}

        for pr in change.prs:
            if pr.author:
                pr_authors_by_pr_number[pr.number] = pr.author

                # Add to final map immediately
                final_authors_map[pr.author.get_identifier()] = pr.author

                # Index for matching
                if pr.author.name:
                    known_authors_by_name[pr.author.name] = pr.author
                if pr.author.email:
                    known_authors_by_email[pr.author.email] = pr.author

        # 2. Process commits and try to link them to existing PR authors
        for commit in change.commits:
            resolved_author = commit.author

            # Strategy A: Link via PR number (Strongest link)
            if commit.pr_number and commit.pr_number in pr_authors_by_pr_number:
                resolved_author = pr_authors_by_pr_number[commit.pr_number]

            # Strategy B: Link via Email (Strong link, if available)
            elif commit.author.email and commit.author.email in known_authors_by_email:
                resolved_author = known_authors_by_email[commit.author.email]

            # Strategy C: Link via Name (Weaker link, but helps if email is missing)
            elif commit.author.name and commit.author.name in known_authors_by_name:
                resolved_author = known_authors_by_name[commit.author.name]

            # Add to map (deduplicates by identifier)
            # If we resolved to a PR author, get_identifier() returns username.
            # If we stayed with commit author, get_identifier() returns name/email.
            final_authors_map[resolved_author.get_identifier()] = resolved_author

        return list(final_authors_map.values())

    def _determine_category(
        self,
        change: ConsolidatedChange,
        issue: Optional[Issue]
    ) -> Optional[str]:
        """Determine the category for a change based on labels with source prefix support."""
        # Get labels from issue with source indicator
        issue_labels: List[str] = []
        pr_labels: List[str] = []

        if issue:
            issue_labels = [label.name for label in issue.labels]

        if change.prs:
            for pr in change.prs:
                pr_labels.extend([label.name for label in pr.labels])

        # Check against category mappings (respecting pr: and issue: prefixes)
        for category_config in self.config.release_notes.categories:
            # Check issue labels
            for label in issue_labels:
                if category_config.matches_label(label, "issue"):
                    return category_config.name

            # Check PR labels
            for label in pr_labels:
                if category_config.matches_label(label, "pr"):
                    return category_config.name

        return self._get_fallback_category_name()

    def _extract_section(self, text: str, regex: Optional[str]) -> Optional[str]:
        """Extract a section from text using regex."""
        if not regex or not text:
            return None

        match = re.search(regex, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_github_url_info(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract repository name and number from a GitHub URL.

        Args:
            url: GitHub URL (e.g., "https://github.com/owner/repo/issues/1234")

        Returns:
            Tuple of (owner_repo, number) where owner_repo is "owner/repo" format
            and number is the issue/PR number as a string.
            Returns (None, None) if URL is not a valid GitHub URL.

        Examples:
            "https://github.com/sequentech/meta/issues/8853" -> ("sequentech/meta", "8853")
            "https://github.com/owner/repo/pull/123" -> ("owner/repo", "123")
        """
        # Pattern: https://github.com/owner/repo/(issues|pull)/number
        pattern = r'github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)'
        match = re.search(pattern, url)

        if match:
            owner = match.group(1)       # Owner name (e.g., "sequentech")
            repo = match.group(2)        # Repo name (e.g., "meta")
            number = match.group(4)      # The issue/PR number
            owner_repo = f"{owner}/{repo}"
            return (owner_repo, number)

        return (None, None)

    def group_by_category(
        self,
        notes: List[ReleaseNote]
    ) -> Dict[str, List[ReleaseNote]]:
        """Group release notes by category."""
        # Filter out excluded notes
        excluded_labels = set(self.config.release_notes.excluded_labels)
        notes = [
            note for note in notes
            if not any(label in excluded_labels for label in note.labels)
        ]

        # Group by category
        grouped: Dict[str, List[ReleaseNote]] = {}
        for category_name in self.config.get_ordered_categories():
            grouped[category_name] = []

        for note in notes:
            category = note.category or self._get_fallback_category_name()
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(note)

        return grouped

    def _validate_all_notes_rendered(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        rendered_note_count: int,
        context: str = "template rendering"
    ) -> None:
        """
        Validate that all notes from grouped_notes were rendered in the output.

        This helps detect configuration issues where notes are categorized with a name
        that doesn't match any configured category (e.g., hardcoded "Other" fallback
        vs config defining "Other Changes").

        Args:
            grouped_notes: Dict of category name -> list of notes
            rendered_note_count: Number of notes actually added to template context
            context: Description of where this validation is called from (for error messages)

        Warns:
            If rendered count doesn't match total in grouped_notes, issues warning with:
            - Number of missing notes
            - Categories in grouped_notes not found in configured categories
            - Suggestion to check category name configuration
        """
        from rich.console import Console
        console = Console()

        # Count total notes in grouped_notes
        total_notes = sum(len(notes) for notes in grouped_notes.values())

        # Check if counts match
        if rendered_note_count == total_notes:
            return  # All good!

        # We have missing notes - find out which categories are orphaned
        configured_categories = set(self.config.get_ordered_categories())
        grouped_categories = set(grouped_notes.keys())
        orphaned_categories = grouped_categories - configured_categories

        missing_count = total_notes - rendered_note_count

        # Build warning message
        msg_lines = []
        msg_lines.append("")
        msg_lines.append(f"[yellow]⚠️  Warning: {missing_count} note(s) not rendered during {context}[/yellow]")
        msg_lines.append("")
        msg_lines.append(f"  [dim]Total notes in grouped_notes:[/dim] {total_notes}")
        msg_lines.append(f"  [dim]Notes added to template:[/dim] {rendered_note_count}")
        msg_lines.append("")

        if orphaned_categories:
            msg_lines.append(f"  [yellow]Categories in grouped_notes but not in config:[/yellow]")
            for cat in orphaned_categories:
                note_count = len(grouped_notes[cat])
                msg_lines.append(f"    • [bold]{cat}[/bold] ({note_count} note(s))")
            msg_lines.append("")
            msg_lines.append("  [dim]Possible causes:[/dim]")
            msg_lines.append("    1. Category name mismatch between hardcoded fallback and config")
            msg_lines.append("    2. Notes categorized with name not defined in config categories")
            msg_lines.append("")
            msg_lines.append("  [dim]To fix:[/dim]")
            msg_lines.append("    • Check that config defines category with exact name(s) above")
            msg_lines.append("    • Verify fallback category 'Other' is defined in config")
            msg_lines.append("    • Add missing categories to [[release_notes.categories]]")
            msg_lines.append("")

        console.print("\n".join(msg_lines))

    def _process_html_like_whitespace(self, text: str, intermediate_pass: bool = False) -> str:
        """
        Process template output with HTML-like whitespace behavior.

        - Multiple spaces/tabs collapse to single space
        - Newlines are ignored unless using <br> or <br/>
        - &nbsp; entities are preserved as non-breaking spaces
        - Leading/trailing whitespace stripped from lines
        """
        import re

        # 1. Protect &nbsp; entities from whitespace collapse
        processed = text.replace('&nbsp;', '<NBSP_MARKER>')

        # 2. Replace <br> and <br/> with newline markers
        # Use a unique marker that won't conflict with actual content
        processed = processed.replace('<br/>', '<BR_MARKER>').replace('<br>', '<BR_MARKER>')

        # 3. Collapse multiple spaces/tabs into single space (like HTML)
        processed = re.sub(r'[^\S\n]+', ' ', processed)

        # 4. Strip leading/trailing whitespace from each line
        processed = '\n'.join(line.strip() for line in processed.split('\n'))

        # 5. collapse consecutive new lines into a single one
        processed = re.sub(r'([ \t\n])[ \t\n]*', '\\1', processed)

        # 6. Replace markers if final pass
        if not intermediate_pass:
            processed = processed.replace('<NBSP_MARKER>', ' ').replace('<BR_MARKER>', '\n')

        # import pdb; pdb.set_trace()
        return processed

    def _prepare_note_for_template(
        self,
        note: ReleaseNote,
        version: str,
        output_path: Optional[str],
        media_downloader,
        convert_html_to_markdown: bool = False
    ) -> Dict[str, Any]:
        """
        Prepare a release note for template rendering.

        Returns a dict with processed description/migration and author dicts.
        """
        # Process media in description and migration notes if enabled
        processed_description = note.description
        processed_migration = note.migration_notes

        if media_downloader and output_path:
            if note.description:
                processed_description = media_downloader.process_description(
                    note.description, version, output_path, convert_html_to_markdown
                )
            if note.migration_notes:
                processed_migration = media_downloader.process_description(
                    note.migration_notes, version, output_path, convert_html_to_markdown
                )

        # Convert Author objects to dicts for template access
        authors_dicts = [author.to_dict() for author in note.authors]

        return {
            'title': note.title,
            'url': note.url,  # Smart URL: issue_url if available, else pr_url
            'issue_url': note.issue_url,  # Direct issue URL
            'pr_url': note.pr_url,  # Direct PR URL
            'short_link': note.short_link,  # Short format: #1234
            'short_repo_link': note.short_repo_link,  # Short format: owner/repo#1234
            'pr_numbers': note.pr_numbers,
            'authors': authors_dicts,
            'description': processed_description,
            'migration_notes': processed_migration,
            'labels': note.labels,
            'issue_key': note.issue_key,
            'category': note.category,
            'commit_shas': note.commit_shas
        }

    def format_markdown(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_paths: Optional[List[str]] = None
    ):
        """
        Format release notes as markdown using pr_code templates.

        Args:
            grouped_notes: Release notes grouped by category
            version: Version string
            output_paths: Optional list of output file paths (for media processing)

        Returns:
            List of tuples: [(content, output_path), ...]
            For backward compatibility: if only one output, returns just the content string
        """
        from jinja2 import Template
        from .media_utils import MediaDownloader

        results = []

        # Check if pr_code templates are configured (handle both old and new format)
        # New format: pr_code is Dict[str, PRCodeConfig]
        # For backward compatibility with direct method calls, check if any repo has templates
        has_pr_code_templates = False
        pr_code_templates = []

        if isinstance(self.config.output.pr_code, dict):
            # New multi-repo format
            # Collect all templates from all repos
            for repo_alias, pr_code_config in self.config.output.pr_code.items():
                if pr_code_config.templates:
                    has_pr_code_templates = True
                    pr_code_templates.extend(pr_code_config.templates)

        if has_pr_code_templates:
            # Use pr_code templates
            for i, template_config in enumerate(pr_code_templates):
                # Get output path (from output_paths list or from template config)
                output_path = None
                if output_paths and i < len(output_paths):
                    output_path = output_paths[i]

                # Initialize media downloader if enabled
                media_downloader = None
                if self.config.output.download_media and output_path:
                    media_downloader = MediaDownloader(
                        self.config.output.assets_path,
                        download_enabled=True
                    )

                # Render the template
                content = self._format_with_pr_code_template(
                    template_config.output_template,
                    grouped_notes,
                    version,
                    output_path,
                    media_downloader
                )

                results.append((content, output_path))

            # Check if there's an additional output_path for draft file (added by generate.py)
            # This happens when pr_code templates are configured but we also need a draft file
            num_templates = len(pr_code_templates)
            if output_paths and len(output_paths) > num_templates:
                # Generate draft file using standard release notes template
                draft_path = output_paths[num_templates]  # The extra path is the draft

                # Initialize media downloader if enabled
                draft_media_downloader = None
                if self.config.output.download_media and draft_path:
                    draft_media_downloader = MediaDownloader(
                        self.config.output.assets_path,
                        download_enabled=True
                    )

                # Generate standard release notes for draft
                draft_content = self._format_with_master_template(
                    grouped_notes,
                    version,
                    draft_path,
                    draft_media_downloader
                )

                results.append((draft_content, draft_path))

        # Backward compatibility: support doc_output_template
        elif self.config.release_notes.doc_output_template:
            # Generate base release notes first
            release_output_path = output_paths[0] if output_paths and len(output_paths) > 0 else None
            doc_output_path = output_paths[1] if output_paths and len(output_paths) > 1 else None

            media_downloader = None
            if self.config.output.download_media and release_output_path:
                media_downloader = MediaDownloader(
                    self.config.output.assets_path,
                    download_enabled=True
                )

            release_notes = self._format_with_master_template(
                grouped_notes, version, release_output_path, media_downloader
            )

            # Create doc notes with doc_output_template
            doc_media_downloader = None
            if self.config.output.download_media and doc_output_path:
                doc_media_downloader = MediaDownloader(
                    self.config.output.assets_path,
                    download_enabled=True
                )

            doc_notes = self._format_with_doc_template(
                grouped_notes, version, doc_output_path, doc_media_downloader, release_notes
            )

            # Return legacy tuple format
            return (release_notes, doc_notes)

        else:
            # No templates configured - return base release notes
            output_path = output_paths[0] if output_paths and len(output_paths) > 0 else None
            media_downloader = None
            if self.config.output.download_media and output_path:
                media_downloader = MediaDownloader(
                    self.config.output.assets_path,
                    download_enabled=True
                )

            release_notes = self._format_with_master_template(
                grouped_notes, version, output_path, media_downloader
            )
            return release_notes

        # Return list of tuples for new pr_code template approach
        if len(results) == 1:
            # Single result: return just content for backward compatibility
            return results[0][0]
        return results

    def _format_with_pr_code_template(
        self,
        template_str: str,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader
    ) -> str:
        """
        Format using a pr_code template.

        Args:
            template_str: The Jinja2 template string
            grouped_notes: Release notes grouped by category
            version: Version string
            output_path: Output file path (for media processing)
            media_downloader: Media downloader instance

        Returns:
            Rendered template content
        """
        from jinja2 import Template

        # Create entry template for sub-rendering
        entry_template = Template(self.config.release_notes.entry_template)

        # Create a render_entry function
        def render_entry(note_dict: Dict[str, Any]) -> str:
            """Render a single entry using the entry_template."""
            rendered = entry_template.render(**note_dict)
            return self._process_html_like_whitespace(rendered, intermediate_pass=True)

        # Prepare all notes with processed data
        categories_data = []
        all_notes_data = []

        for category_name in self.config.get_ordered_categories():
            notes = grouped_notes.get(category_name, [])
            if not notes:
                continue

            notes_data = []
            for note in notes:
                note_dict = self._prepare_note_for_template(
                    note, version, output_path, media_downloader
                )
                notes_data.append(note_dict)
                all_notes_data.append(note_dict)

            # Find category config for alias
            category_alias = None
            for cat_config in self.config.release_notes.categories:
                if cat_config.name == category_name:
                    category_alias = cat_config.alias
                    break

            categories_data.append({
                'name': category_name,
                'alias': category_alias,
                'notes': notes_data
            })

        # Validate that all notes were rendered
        self._validate_all_notes_rendered(
            grouped_notes,
            len(all_notes_data),
            context="pr_code template rendering"
        )

        # Render title
        title_template = Template(self.config.release_notes.title_template)
        title = title_template.render(version=version)

        # Create render_release_notes function that renders the base release notes
        def render_release_notes() -> str:
            """Render the base release notes content using the configured template."""
            base_template = Template(self.config.release_notes.release_output_template)
            output = base_template.render(
                version=version,
                title=title,
                categories=categories_data,
                all_notes=all_notes_data,
                render_entry=render_entry
            )
            return self._process_html_like_whitespace(output, intermediate_pass=True)

        # Parse version to extract components
        try:
            sem_ver = SemanticVersion.parse(version)
            major = sem_ver.major
            minor = sem_ver.minor
            patch = sem_ver.patch
            prerelease = sem_ver.prerelease or ""
        except Exception as e:
            # If version parsing fails, set empty values
            console.print(f"[yellow]Warning: Could not parse version '{version}' for template variables: {e}[/yellow]")
            major = ""
            minor = ""
            patch = ""
            prerelease = ""

        # Render the pr_code template
        from datetime import datetime
        pr_code_template = Template(template_str)
        output = pr_code_template.render(
            version=version,
            major=major,
            minor=minor,
            patch=patch,
            prerelease=prerelease,
            title=title,
            categories=categories_data,
            all_notes=all_notes_data,
            render_entry=render_entry,
            render_release_notes=render_release_notes,
            year=datetime.now().year
        )

        # Process HTML-like whitespace
        output = self._process_html_like_whitespace(output, intermediate_pass=False)

        return output

    def _format_with_master_template(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader,
        intermediate_pass: bool = False
    ) -> str:
        """Format using the configured release_output_template."""
        from jinja2 import Template

        # Create entry template for sub-rendering
        entry_template = Template(self.config.release_notes.entry_template)

        # Create a render_entry function that can be called from the master template
        def render_entry(note_dict: Dict[str, Any]) -> str:
            """Render a single entry using the entry_template."""
            rendered = entry_template.render(**note_dict)
            return self._process_html_like_whitespace(rendered, intermediate_pass=True)

        # Prepare all notes with processed data
        categories_data = []
        all_notes_data = []

        for category_name in self.config.get_ordered_categories():
            notes = grouped_notes.get(category_name, [])
            if not notes:
                continue

            notes_data = []
            for note in notes:
                note_dict = self._prepare_note_for_template(
                    note, version, output_path, media_downloader
                )
                notes_data.append(note_dict)
                all_notes_data.append(note_dict)

            # Find category config for alias
            category_alias = None
            for cat_config in self.config.release_notes.categories:
                if cat_config.name == category_name:
                    category_alias = cat_config.alias
                    break

            categories_data.append({
                'name': category_name,
                'alias': category_alias,
                'notes': notes_data
            })

        # Validate that all notes were rendered
        self._validate_all_notes_rendered(
            grouped_notes,
            len(all_notes_data),
            context="master template rendering"
        )

        # Render title
        title_template = Template(self.config.release_notes.title_template)
        title = title_template.render(version=version)

        # Render master template using configured release_output_template
        from datetime import datetime
        master_template = Template(self.config.release_notes.release_output_template)
        output = master_template.render(
            version=version,
            title=title,
            categories=categories_data,
            all_notes=all_notes_data,
            render_entry=render_entry,
            year=datetime.now().year
        )

        # Process HTML-like whitespace WITHOUT intermediate_pass
        # This will convert <br> tags to proper newlines without extra blank lines
        output = self._process_html_like_whitespace(output, intermediate_pass=False)

        return output

    def _format_with_doc_template(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader,
        release_notes: str
    ) -> str:
        """Format using the doc_output_template with render_release_notes() function."""
        from jinja2 import Template

        # Create entry template for sub-rendering
        entry_template = Template(self.config.release_notes.entry_template)

        # Create a render_entry function
        def render_entry(note_dict: Dict[str, Any]) -> str:
            """Render a single entry using the entry_template."""
            rendered = entry_template.render(**note_dict)
            return self._process_html_like_whitespace(rendered, intermediate_pass=True)

        # Create a render_release_notes function that returns the already-rendered release notes
        # wrapped in a marker to prevent re-processing
        def render_release_notes() -> str:
            """Render the GitHub release notes (already computed)."""
            # Return the release notes wrapped in a marker to protect from re-processing
            return release_notes

        # Prepare all notes with processed data
        categories_data = []
        all_notes_data = []

        for category_name in self.config.get_ordered_categories():
            notes = grouped_notes.get(category_name, [])
            if not notes:
                continue

            notes_data = []
            for note in notes:
                note_dict = self._prepare_note_for_template(
                    note, version, output_path, media_downloader,
                    convert_html_to_markdown=True  # Convert HTML img tags to Markdown for docs
                )
                notes_data.append(note_dict)
                all_notes_data.append(note_dict)

            # Find category config for alias
            category_alias = None
            for cat_config in self.config.release_notes.categories:
                if cat_config.name == category_name:
                    category_alias = cat_config.alias
                    break

            categories_data.append({
                'name': category_name,
                'alias': category_alias,
                'notes': notes_data
            })

        # Render title
        title_template = Template(self.config.release_notes.title_template)
        title = title_template.render(version=version)

        # Render doc template
        from datetime import datetime
        doc_template = Template(self.config.release_notes.doc_output_template)
        output = doc_template.render(
            version=version,
            title=title,
            categories=categories_data,
            all_notes=all_notes_data,
            render_entry=render_entry,
            render_release_notes=render_release_notes,
            year=datetime.now().year
        )

        # Process HTML-like whitespace WITHOUT intermediate_pass
        # This will convert <br> tags to proper newlines without extra blank lines
        output = self._process_html_like_whitespace(output, intermediate_pass=False)
        
        return output

    def _format_with_legacy_layout(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader,
        intermediate_pass: bool = False
    ) -> str:
        """Format using the legacy category-based layout."""
        from jinja2 import Template

        lines = []
        rendered_note_count = 0

        # Title
        title_template = Template(self.config.release_notes.title_template)
        title = title_template.render(version=version)
        lines.append(f"# {title}")
        lines.append("")

        # Description (legacy)
        if self.config.release_notes.description_template:
            desc_template = Template(self.config.release_notes.description_template)
            description = desc_template.render(version=version)
            lines.append(description)
            lines.append("")

        # Categories
        entry_template = Template(self.config.release_notes.entry_template)

        for category in self.config.get_ordered_categories():
            notes = grouped_notes.get(category, [])
            if not notes:
                continue

            lines.append(f"## {category}")
            lines.append("")

            for note in notes:
                note_dict = self._prepare_note_for_template(
                    note, version, output_path, media_downloader
                )

                rendered_entry = entry_template.render(**note_dict)
                processed_entry = self._process_html_like_whitespace(rendered_entry, intermediate_pass=True)
                lines.append(processed_entry)

                # Add description if present and not already in template
                if note_dict['description'] and '{{ description }}' not in self.config.release_notes.entry_template:
                    lines.append(f"  {note_dict['description'][:200]}...")
                    lines.append("")

                rendered_note_count += 1

            lines.append("")

        # Validate that all notes were rendered
        self._validate_all_notes_rendered(
            grouped_notes,
            rendered_note_count,
            context="legacy layout rendering"
        )

        output = "\n".join(lines)

        # Replace &nbsp; markers with actual spaces (done at the very end)
        output = output.replace('<NBSP_MARKER>', ' ')

        return output


class VersionGapChecker:
    """Check for version gaps."""

    def __init__(self, config: Config):
        self.config = config

    def check_gap(self, from_version: str, to_version: str):
        """Check if there's a gap between versions."""
        from .models import SemanticVersion

        action = self.config.version_policy.gap_detection
        if action == PolicyAction.IGNORE:
            return

        try:
            prev = SemanticVersion.parse(from_version)
            curr = SemanticVersion.parse(to_version)

            gap = False
            if curr.major > prev.major + 1:
                gap = True
            elif curr.major == prev.major and curr.minor > prev.minor + 1:
                gap = True
            elif (curr.major == prev.major and
                  curr.minor == prev.minor and
                  curr.patch > prev.patch + 1):
                gap = True

            if gap:
                msg = f"Version gap detected between {from_version} and {to_version}"
                if action == PolicyAction.ERROR:
                    raise ValueError(msg)
                elif action == PolicyAction.WARN:
                    console.print(f"[yellow]WARNING: {msg}[/yellow]")

        except ValueError as e:
            if action == PolicyAction.ERROR:
                raise
            elif action == PolicyAction.WARN:
                console.print(f"[yellow]WARNING: {e}[/yellow]")
