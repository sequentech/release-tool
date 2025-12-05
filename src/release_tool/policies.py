# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Policy implementations for ticket extraction, consolidation, and release notes."""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from enum import Enum
from rich.console import Console

from .models import (
    Commit, PullRequest, Ticket, ReleaseNote, ConsolidatedChange, Label
)
from .config import (
    Config, PolicyAction, TicketExtractionStrategy
)

console = Console()


class PartialTicketReason(Enum):
    """Reasons why a ticket might be partially matched."""

    # Not found reasons
    OLDER_THAN_CUTOFF = "older_than_cutoff"  # Ticket may be older than sync cutoff date
    TYPO = "typo"  # Ticket may not exist (typo in branch/PR)
    SYNC_NOT_RUN = "sync_not_run"  # Sync may not have been run yet

    # Different repo reasons
    REPO_CONFIG_MISMATCH = "repo_config_mismatch"  # Ticket found in different repo than configured
    WRONG_TICKET_REPOS = "wrong_ticket_repos"  # Mismatch between ticket_repos config and actual location

    @property
    def description(self) -> str:
        """Get human-readable description of the reason."""
        descriptions = {
            PartialTicketReason.OLDER_THAN_CUTOFF: "Ticket may be older than sync cutoff date",
            PartialTicketReason.TYPO: "Ticket may not exist (typo in branch/PR)",
            PartialTicketReason.SYNC_NOT_RUN: "Sync may not have been run yet",
            PartialTicketReason.REPO_CONFIG_MISMATCH: "Ticket found in different repo than configured",
            PartialTicketReason.WRONG_TICKET_REPOS: "Check repository.ticket_repos in config",
        }
        return descriptions.get(self, self.value)


@dataclass
class PartialTicketMatch:
    """
    Information about a partial ticket match.

    A partial match occurs when a ticket is extracted from a branch/PR/commit
    but cannot be fully resolved to a ticket in the database, or is found
    in an unexpected repository.
    """
    ticket_key: str  # The extracted ticket key (e.g., "8624", "#123")
    extracted_from: str  # Human-readable description of source (e.g., "branch feat/meta-8624/main, pattern #1")
    match_type: str  # "not_found" or "different_repo"
    found_in_repo: Optional[str] = None  # For different_repo type: which repo it was found in
    ticket_url: Optional[str] = None  # For different_repo type: URL to the ticket
    potential_reasons: Set[PartialTicketReason] = field(default_factory=set)  # Set of potential causes


class TicketExtractor:
    """Extract ticket references from various sources."""

    def __init__(self, config: Config, debug: bool = False):
        self.config = config
        self.debug = debug
        # Sort patterns by order field, then group by strategy for efficient lookup
        sorted_patterns = sorted(config.ticket_policy.patterns, key=lambda p: p.order)
        self.pattern_configs = sorted_patterns  # Store for debug output
        self.patterns_by_strategy: Dict[TicketExtractionStrategy, List[re.Pattern]] = {}
        for ticket_pattern in sorted_patterns:
            strategy = ticket_pattern.strategy
            if strategy not in self.patterns_by_strategy:
                self.patterns_by_strategy[strategy] = []
            self.patterns_by_strategy[strategy].append(re.compile(ticket_pattern.pattern))

    def _extract_with_patterns(self, text: str, patterns: List[re.Pattern], show_results: bool = False) -> List[str]:
        """Extract ticket references using a list of patterns."""
        tickets = []
        for i, pattern in enumerate(patterns):
            matches_found = []
            # Use finditer to get match objects and extract named groups
            for match in pattern.finditer(text):
                # Try to extract the 'ticket' named group
                try:
                    ticket = match.group('ticket')
                    tickets.append(ticket)
                    matches_found.append(ticket)
                except IndexError:
                    # If no 'ticket' group, fall back to the entire match or first group
                    if match.groups():
                        ticket = match.group(1)
                        tickets.append(ticket)
                        matches_found.append(ticket)
                    else:
                        ticket = match.group(0)
                        tickets.append(ticket)
                        matches_found.append(ticket)

            if self.debug and show_results:
                if matches_found:
                    console.print(f"    [green]✅ MATCH! Extracted: {matches_found}[/green]")
                else:
                    console.print(f"    [dim]❌ No match[/dim]")

        return tickets

    def extract_from_commit(self, commit: Commit) -> List[str]:
        """Extract ticket references from commit message."""
        if self.debug:
            console.print(f"\n🔍 [bold cyan]Extracting from commit:[/bold cyan] {commit.sha[:7]} - {commit.message[:60]}{'...' if len(commit.message) > 60 else ''}")

        patterns = self.patterns_by_strategy.get(TicketExtractionStrategy.COMMIT_MESSAGE, [])

        # Debug: show which patterns apply to commit_message
        if self.debug and patterns:
            matching_configs = [p for p in self.pattern_configs if p.strategy == TicketExtractionStrategy.COMMIT_MESSAGE]
            for pattern_config in matching_configs:
                console.print(f"  [dim]Trying pattern #{pattern_config.order} (strategy={pattern_config.strategy.value})[/dim]")
                if pattern_config.description:
                    console.print(f"    Description: \"{pattern_config.description}\"")
                console.print(f"    Regex: {pattern_config.pattern}")
                console.print(f"    Text: \"{commit.message[:100]}{'...' if len(commit.message) > 100 else ''}\"")

        tickets = list(set(self._extract_with_patterns(commit.message, patterns, show_results=self.debug)))

        if self.debug:
            if tickets:
                console.print(f"  [green]✅ Extracted tickets: {tickets}[/green]")
            else:
                console.print(f"  [yellow]- Extracted tickets: (none)[/yellow]")

        return tickets

    def extract_from_pr(self, pr: PullRequest) -> List[str]:
        """Extract ticket references from PR using configured strategies."""
        if self.debug:
            console.print(f"\n🔍 [bold cyan]Extracting from PR #{pr.number}:[/bold cyan] {pr.title[:60]}{'...' if len(pr.title) > 60 else ''}")

        tickets = []

        # Try patterns in order (sorted by order field)
        sorted_patterns = sorted(self.config.ticket_policy.patterns, key=lambda p: p.order)
        for ticket_pattern in sorted_patterns:
            strategy = ticket_pattern.strategy
            text = None
            source_name = None

            if strategy == TicketExtractionStrategy.PR_BODY and pr.body:
                text = pr.body
                source_name = "pr_body"
            elif strategy == TicketExtractionStrategy.PR_TITLE and pr.title:
                text = pr.title
                source_name = "pr_title"
            elif strategy == TicketExtractionStrategy.BRANCH_NAME and pr.head_branch:
                text = pr.head_branch
                source_name = "branch_name"

            if self.debug:
                console.print(f"  [dim]Pattern #{ticket_pattern.order} (strategy={strategy.value})[/dim]")
                if ticket_pattern.description:
                    console.print(f"    Description: \"{ticket_pattern.description}\"")
                console.print(f"    Regex: {ticket_pattern.pattern}")

            if text:
                if self.debug:
                    console.print(f"    Source: {source_name}")
                    console.print(f"    Text: \"{text[:100]}{'...' if len(text) > 100 else ''}\"")

                pattern = re.compile(ticket_pattern.pattern)
                extracted = self._extract_with_patterns(text, [pattern], show_results=self.debug)
                if extracted:
                    tickets.extend(extracted)
                    if self.debug:
                        console.print(f"    [yellow]🛑 Stopping (first match wins)[/yellow]")
                    # Stop on first match to respect priority order
                    break
            else:
                if self.debug:
                    console.print(f"    [dim]❌ Skipped (no {strategy.value} available)[/dim]")

        if self.debug:
            if tickets:
                console.print(f"  [green]✅ Extracted tickets: {list(set(tickets))}[/green]")
            else:
                console.print(f"  [yellow]- Extracted tickets: (none)[/yellow]")

        return list(set(tickets))

    def extract_from_branch(self, branch_name: str) -> List[str]:
        """Extract ticket references from branch name."""
        if self.debug:
            console.print(f"\n🔍 [bold cyan]Extracting from branch:[/bold cyan] {branch_name}")

        patterns = self.patterns_by_strategy.get(TicketExtractionStrategy.BRANCH_NAME, [])

        # Debug: show which patterns apply to branch_name
        if self.debug and patterns:
            matching_configs = [p for p in self.pattern_configs if p.strategy == TicketExtractionStrategy.BRANCH_NAME]
            for pattern_config in matching_configs:
                console.print(f"  [dim]Trying pattern #{pattern_config.order} (strategy={pattern_config.strategy.value})[/dim]")
                if pattern_config.description:
                    console.print(f"    Description: \"{pattern_config.description}\"")
                console.print(f"    Regex: {pattern_config.pattern}")
                console.print(f"    Text: \"{branch_name}\"")

        tickets = list(set(self._extract_with_patterns(branch_name, patterns, show_results=self.debug)))

        if self.debug:
            if tickets:
                console.print(f"  [green]✅ Extracted tickets: {tickets}[/green]")
            else:
                console.print(f"  [yellow]- Extracted tickets: (none)[/yellow]")

        return tickets


class CommitConsolidator:
    """Consolidate commits by parent ticket."""

    def __init__(self, config: Config, extractor: TicketExtractor, debug: bool = False):
        self.config = config
        self.extractor = extractor
        self.debug = debug

    def consolidate(
        self,
        commits: List[Commit],
        prs: Dict[int, PullRequest]
    ) -> List[ConsolidatedChange]:
        """
        Consolidate commits by their parent ticket.

        Returns a list of ConsolidatedChange objects, grouped by ticket.
        """
        if not self.config.ticket_policy.consolidation_enabled:
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

            # Try to find ticket from commit
            tickets = self.extractor.extract_from_commit(commit)

            if self.debug:
                console.print(f"  → Tickets from commit: {tickets if tickets else '(none)'}")

            # Try to find associated PR
            pr = prs.get(commit.pr_number) if commit.pr_number else None
            if pr:
                if self.debug:
                    console.print(f"  ✅ Associated PR: #{pr.number} \"{pr.title[:50]}{'...' if len(pr.title) > 50 else ''}\"")
                pr_tickets = self.extractor.extract_from_pr(pr)
                if self.debug:
                    console.print(f"  {'✅' if pr_tickets else '→'} Tickets from PR: {pr_tickets if pr_tickets else '(none)'}")
                tickets.extend(pr_tickets)
            elif self.debug:
                console.print(f"  → Associated PR: (none)")

            tickets = list(set(tickets))  # Remove duplicates

            if tickets:
                # Use first ticket as the parent
                ticket_key = tickets[0]
                if self.debug:
                    console.print(f"  [green]✅ Consolidated under ticket: {ticket_key}[/green]")

                if ticket_key not in consolidated:
                    consolidated[ticket_key] = ConsolidatedChange(
                        type="ticket",
                        ticket_key=ticket_key,
                        commits=[],
                        prs=[]
                    )
                consolidated[ticket_key].commits.append(commit)
                if pr and pr not in consolidated[ticket_key].prs:
                    consolidated[ticket_key].prs.append(pr)
            elif pr:
                # No ticket but has PR
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
                # No ticket and no PR - standalone commit
                commit_key = f"commit-{commit.sha[:8]}"
                if self.debug:
                    console.print(f"  [dim]- Standalone commit (no ticket or PR)[/dim]")

                consolidated[commit_key] = ConsolidatedChange(
                    type="commit",
                    commits=[commit]
                )

        return list(consolidated.values())

    def handle_missing_tickets(
        self,
        consolidated_changes: List[ConsolidatedChange]
    ):
        """Handle changes that don't have a parent ticket."""
        action = self.config.ticket_policy.no_ticket_action
        no_ticket_changes = [
            c for c in consolidated_changes
            if c.type in ["commit", "pr"] or not c.ticket_key
        ]

        if not no_ticket_changes:
            return

        if action == PolicyAction.ERROR:
            raise ValueError(
                f"Found {len(no_ticket_changes)} changes without a parent ticket. "
                "Configure no_ticket_action policy to allow this."
            )
        elif action == PolicyAction.WARN:
            console.print(
                f"[yellow]WARNING: Found {len(no_ticket_changes)} changes without a parent ticket[/yellow]"
            )
            for change in no_ticket_changes[:5]:  # Show first 5
                if change.commits:
                    msg = change.commits[0].message.split('\n')[0]
                    console.print(f"  - {msg[:80]}")


class ReleaseNoteGenerator:
    """Generate release notes from consolidated changes."""

    def __init__(self, config: Config):
        self.config = config

    def create_release_note(
        self,
        change: ConsolidatedChange,
        ticket: Optional[Ticket] = None
    ) -> ReleaseNote:
        """Create a release note from a consolidated change."""
        # Extract and deduplicate authors from commits and PRs
        authors = self._deduplicate_authors(change)
        
        pr_numbers = list(set(pr.number for pr in change.prs))
        commit_shas = [commit.sha for commit in change.commits]

        # Determine title
        if ticket:
            title = ticket.title
        elif change.prs:
            title = change.prs[0].title
        elif change.commits:
            title = change.commits[0].message.split('\n')[0]
        else:
            title = "Unknown change"

        # Determine category from labels
        category = self._determine_category(change, ticket)

        # Extract description and migration notes if we have a ticket
        description = None
        migration_notes = None
        if ticket and ticket.body:
            description = self._extract_section(
                ticket.body,
                self.config.ticket_policy.description_section_regex
            )
            migration_notes = self._extract_section(
                ticket.body,
                self.config.ticket_policy.migration_section_regex
            )

        # Get URLs
        ticket_url = None
        pr_url = None
        url = None  # Smart URL: ticket_url if available, else pr_url

        if ticket:
            ticket_url = ticket.url
            url = ticket_url  # Prefer ticket URL

        if change.prs:
            pr_url = change.prs[0].url
            if not url:  # Use PR URL if no ticket URL
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
        if ticket:
            labels = [label.name for label in ticket.labels]
        elif change.prs:
            labels = [label.name for pr in change.prs for label in pr.labels]

        return ReleaseNote(
            ticket_key=change.ticket_key,
            title=title,
            description=description,
            migration_notes=migration_notes,
            category=category,
            labels=labels,
            authors=authors,
            pr_numbers=pr_numbers,
            commit_shas=commit_shas,
            ticket_url=ticket_url,
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
        ticket: Optional[Ticket]
    ) -> Optional[str]:
        """Determine the category for a change based on labels with source prefix support."""
        # Get labels from ticket with source indicator
        ticket_labels: List[str] = []
        pr_labels: List[str] = []

        if ticket:
            ticket_labels = [label.name for label in ticket.labels]

        if change.prs:
            for pr in change.prs:
                pr_labels.extend([label.name for label in pr.labels])

        # Check against category mappings (respecting pr: and ticket: prefixes)
        for category_config in self.config.release_notes.categories:
            # Check ticket labels
            for label in ticket_labels:
                if category_config.matches_label(label, "ticket"):
                    return category_config.name

            # Check PR labels
            for label in pr_labels:
                if category_config.matches_label(label, "pr"):
                    return category_config.name

        return "Other"

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
            category = note.category or "Other"
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(note)

        return grouped

    def _process_html_like_whitespace(self, text: str, preserve_br: bool = False) -> str:
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
        if not preserve_br:
            processed = processed.replace('<br/>', '<BR_MARKER>').replace('<br>', '<BR_MARKER>')

        # 3. Collapse multiple spaces/tabs into single space (like HTML)
        processed = re.sub(r'[^\S\n]+', ' ', processed)

        # 4. Strip leading/trailing whitespace from each line
        processed = '\n'.join(line.strip() for line in processed.split('\n'))

        # 5. Remove empty lines (unless they came from <br> tags)
        # Process line by line and handle BR_MARKER specially
        lines_list = []
        for line in processed.split('\n'):
            # If line contains BR_MARKER, split it and add empty line after
            if '<BR_MARKER>' in line:
                parts = line.split('<BR_MARKER>')
                for i, part in enumerate(parts):
                    if part.strip():
                        lines_list.append(part)
                    # Add empty line after all BR_MARKER occurrences except the last part
                    if i < len(parts) - 1:
                        lines_list.append('')
            elif line.strip():
                lines_list.append(line)
            elif preserve_br:
                lines_list.append('')

        result = '\n'.join(lines_list)

        # Note: We don't replace <NBSP_MARKER> here because the output might be
        # processed again (e.g., entry_template processed, then inserted into
        # output_template which is also processed). Markers are replaced at the
        # very end in the format_markdown methods.

        return result

    def _prepare_note_for_template(
        self,
        note: ReleaseNote,
        version: str,
        output_path: Optional[str],
        media_downloader
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
                    note.description, version, output_path
                )
            if note.migration_notes:
                processed_migration = media_downloader.process_description(
                    note.migration_notes, version, output_path
                )

        # Convert Author objects to dicts for template access
        authors_dicts = [author.to_dict() for author in note.authors]

        return {
            'title': note.title,
            'url': note.url,  # Smart URL: ticket_url if available, else pr_url
            'ticket_url': note.ticket_url,  # Direct ticket URL
            'pr_url': note.pr_url,  # Direct PR URL
            'short_link': note.short_link,  # Short format: #1234
            'short_repo_link': note.short_repo_link,  # Short format: owner/repo#1234
            'pr_numbers': note.pr_numbers,
            'authors': authors_dicts,
            'description': processed_description,
            'migration_notes': processed_migration,
            'labels': note.labels,
            'ticket_key': note.ticket_key,
            'category': note.category,
            'commit_shas': note.commit_shas
        }

    def format_markdown(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        release_output_path: Optional[str] = None,
        doc_output_path: Optional[str] = None
    ):
        """
        Format release notes as markdown.

        Args:
            grouped_notes: Release notes grouped by category
            version: Version string
            release_output_path: Optional GitHub release notes output file path (for media processing)
            doc_output_path: Optional Docusaurus output file path (for media processing)

        Returns:
            If doc_output_template is configured: tuple of (release_notes, doc_notes)
            Otherwise: single release notes string
        """
        from jinja2 import Template
        from .media_utils import MediaDownloader

        # Initialize media downloader if enabled (use release_output_path for media)
        media_downloader = None
        if self.config.output.download_media and release_output_path:
            media_downloader = MediaDownloader(
                self.config.output.assets_path,
                download_enabled=True
            )

        # If release_output_template is configured, use master template approach
        if self.config.release_notes.release_output_template:
            release_notes = self._format_with_master_template(
                grouped_notes, version, release_output_path, media_downloader
            )
        else:
            # Otherwise, use legacy approach for backward compatibility
            release_notes = self._format_with_legacy_layout(
                grouped_notes, version, release_output_path, media_downloader
            )

        # If doc_output_template is configured, generate Docusaurus version as well
        if self.config.release_notes.doc_output_template:
            doc_notes = self._format_with_doc_template(
                grouped_notes, version, doc_output_path, media_downloader, release_notes
            )
            return (release_notes, doc_notes)

        # Return just release notes if no doc template
        return release_notes

    def _format_with_master_template(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader,
        preserve_br: bool = False
    ) -> str:
        """Format using the master release_output_template."""
        from jinja2 import Template

        # Create entry template for sub-rendering
        entry_template = Template(self.config.release_notes.entry_template)

        # Create a render_entry function that can be called from the master template
        def render_entry(note_dict: Dict[str, Any]) -> str:
            """Render a single entry using the entry_template."""
            rendered = entry_template.render(**note_dict)
            return self._process_html_like_whitespace(rendered, preserve_br=preserve_br)

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

        # Render title
        title_template = Template(self.config.release_notes.title_template)
        title = title_template.render(version=version)

        # Render master template
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

        # Process HTML-like whitespace
        output = self._process_html_like_whitespace(output)

        # Replace &nbsp; markers with actual spaces (done at the very end)
        output = output.replace('<NBSP_MARKER>', ' ')

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
            return self._process_html_like_whitespace(rendered)

        # Create a render_release_notes function that returns the already-rendered release notes
        # wrapped in a marker to prevent re-processing
        def render_release_notes(preserve_br: bool = True) -> str:
            """Render the GitHub release notes (already computed)."""
            # Return the release notes wrapped in a marker to protect from re-processing
            return '<RELEASE_NOTES_MARKER>'

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

        # Process HTML-like whitespace WITHOUT preserve_br
        # This will convert <br> tags to proper newlines without extra blank lines
        output = self._process_html_like_whitespace(output, preserve_br=False)
        
        # Replace the marker with the actual release notes AFTER processing
        # This way the release notes won't be re-processed
        output = output.replace('<RELEASE_NOTES_MARKER>', release_notes)

        # Replace &nbsp; markers with actual spaces (done at the very end)
        output = output.replace('<NBSP_MARKER>', ' ')

        return output

    def _format_with_legacy_layout(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader,
        preserve_br: bool = False
    ) -> str:
        """Format using the legacy category-based layout."""
        from jinja2 import Template

        lines = []

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
                processed_entry = self._process_html_like_whitespace(rendered_entry, preserve_br=preserve_br)
                lines.append(processed_entry)

                # Add description if present and not already in template
                if note_dict['description'] and '{{ description }}' not in self.config.release_notes.entry_template:
                    lines.append(f"  {note_dict['description'][:200]}...")
                    lines.append("")

            lines.append("")

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
