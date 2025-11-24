"""Policy implementations for ticket extraction, consolidation, and release notes."""

import re
from typing import List, Dict, Optional, Any
from rich.console import Console

from .models import (
    Commit, PullRequest, Ticket, ReleaseNote, ConsolidatedChange, Label
)
from .config import (
    Config, PolicyAction, TicketExtractionStrategy
)

console = Console()


class TicketExtractor:
    """Extract ticket references from various sources."""

    def __init__(self, config: Config):
        self.config = config
        # Sort patterns by order field, then group by strategy for efficient lookup
        sorted_patterns = sorted(config.ticket_policy.patterns, key=lambda p: p.order)
        self.patterns_by_strategy: Dict[TicketExtractionStrategy, List[re.Pattern]] = {}
        for ticket_pattern in sorted_patterns:
            strategy = ticket_pattern.strategy
            if strategy not in self.patterns_by_strategy:
                self.patterns_by_strategy[strategy] = []
            self.patterns_by_strategy[strategy].append(re.compile(ticket_pattern.pattern))

    def _extract_with_patterns(self, text: str, patterns: List[re.Pattern]) -> List[str]:
        """Extract ticket references using a list of patterns."""
        tickets = []
        for pattern in patterns:
            # Use finditer to get match objects and extract named groups
            for match in pattern.finditer(text):
                # Try to extract the 'ticket' named group
                try:
                    ticket = match.group('ticket')
                    tickets.append(ticket)
                except IndexError:
                    # If no 'ticket' group, fall back to the entire match or first group
                    if match.groups():
                        tickets.append(match.group(1))
                    else:
                        tickets.append(match.group(0))
        return tickets

    def extract_from_commit(self, commit: Commit) -> List[str]:
        """Extract ticket references from commit message."""
        patterns = self.patterns_by_strategy.get(TicketExtractionStrategy.COMMIT_MESSAGE, [])
        return list(set(self._extract_with_patterns(commit.message, patterns)))

    def extract_from_pr(self, pr: PullRequest) -> List[str]:
        """Extract ticket references from PR using configured strategies."""
        tickets = []

        # Try patterns in order (sorted by order field)
        sorted_patterns = sorted(self.config.ticket_policy.patterns, key=lambda p: p.order)
        for ticket_pattern in sorted_patterns:
            strategy = ticket_pattern.strategy
            text = None

            if strategy == TicketExtractionStrategy.PR_BODY and pr.body:
                text = pr.body
            elif strategy == TicketExtractionStrategy.PR_TITLE and pr.title:
                text = pr.title
            elif strategy == TicketExtractionStrategy.BRANCH_NAME and pr.head_branch:
                text = pr.head_branch

            if text:
                pattern = re.compile(ticket_pattern.pattern)
                extracted = self._extract_with_patterns(text, [pattern])
                if extracted:
                    tickets.extend(extracted)
                    # Stop on first match to respect priority order
                    break

        return list(set(tickets))

    def extract_from_branch(self, branch_name: str) -> List[str]:
        """Extract ticket references from branch name."""
        patterns = self.patterns_by_strategy.get(TicketExtractionStrategy.BRANCH_NAME, [])
        return list(set(self._extract_with_patterns(branch_name, patterns)))


class CommitConsolidator:
    """Consolidate commits by parent ticket."""

    def __init__(self, config: Config, extractor: TicketExtractor):
        self.config = config
        self.extractor = extractor

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

        for commit in commits:
            # Try to find ticket from commit
            tickets = self.extractor.extract_from_commit(commit)

            # Try to find associated PR
            pr = prs.get(commit.pr_number) if commit.pr_number else None
            if pr:
                pr_tickets = self.extractor.extract_from_pr(pr)
                tickets.extend(pr_tickets)

            tickets = list(set(tickets))  # Remove duplicates

            if tickets:
                # Use first ticket as the parent
                ticket_key = tickets[0]
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
        authors_dict = {}  # Key by best identifier to deduplicate

        # Collect authors from commits
        for commit in change.commits:
            key = commit.author.get_identifier()
            if key not in authors_dict:
                authors_dict[key] = commit.author

        # Collect authors from PRs (may have more complete GitHub info)
        for pr in change.prs:
            if pr.author:
                key = pr.author.get_identifier()
                # PR author may have more complete info, prefer it
                if key not in authors_dict or (pr.author.username and not authors_dict[key].username):
                    authors_dict[key] = pr.author

        authors = list(authors_dict.values())
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
            url=url
        )

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

    def _process_html_like_whitespace(self, text: str) -> str:
        """
        Process template output with HTML-like whitespace behavior.

        - Multiple spaces/tabs collapse to single space
        - Newlines are ignored unless using <br> or <br/>
        - Leading/trailing whitespace stripped from lines
        """
        import re

        # 1. Replace <br> and <br/> with newline markers
        processed = text.replace('<br/>', '\n<BR_MARKER>\n').replace('<br>', '\n<BR_MARKER>\n')

        # 2. Collapse multiple spaces/tabs into single space (like HTML)
        processed = re.sub(r'[^\S\n]+', ' ', processed)

        # 3. Strip leading/trailing whitespace from each line
        processed = '\n'.join(line.strip() for line in processed.split('\n'))

        # 4. Remove empty lines (unless they came from <br> tags)
        lines_list = []
        for line in processed.split('\n'):
            if line == '<BR_MARKER>':
                lines_list.append('')
            elif line.strip():
                lines_list.append(line)

        return '\n'.join(lines_list)

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
        output_path: Optional[str] = None
    ) -> str:
        """
        Format release notes as markdown.

        Args:
            grouped_notes: Release notes grouped by category
            version: Version string
            output_path: Optional output file path (for media processing)

        Returns:
            Formatted markdown string
        """
        from jinja2 import Template
        from .media_utils import MediaDownloader

        # Initialize media downloader if enabled
        media_downloader = None
        if self.config.output.download_media and output_path:
            media_downloader = MediaDownloader(
                self.config.output.assets_path,
                download_enabled=True
            )

        # If output_template is configured, use master template approach
        if self.config.release_notes.output_template:
            return self._format_with_master_template(
                grouped_notes, version, output_path, media_downloader
            )

        # Otherwise, use legacy approach for backward compatibility
        return self._format_with_legacy_layout(
            grouped_notes, version, output_path, media_downloader
        )

    def _format_with_master_template(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader
    ) -> str:
        """Format using the master output_template."""
        from jinja2 import Template

        # Create entry template for sub-rendering
        entry_template = Template(self.config.release_notes.entry_template)

        # Create a render_entry function that can be called from the master template
        def render_entry(note_dict: Dict[str, Any]) -> str:
            """Render a single entry using the entry_template."""
            rendered = entry_template.render(**note_dict)
            return self._process_html_like_whitespace(rendered)

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
        master_template = Template(self.config.release_notes.output_template)
        output = master_template.render(
            version=version,
            title=title,
            categories=categories_data,
            all_notes=all_notes_data,
            render_entry=render_entry
        )

        return self._process_html_like_whitespace(output)

    def _format_with_legacy_layout(
        self,
        grouped_notes: Dict[str, List[ReleaseNote]],
        version: str,
        output_path: Optional[str],
        media_downloader
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
                processed_entry = self._process_html_like_whitespace(rendered_entry)
                lines.append(processed_entry)

                # Add description if present and not already in template
                if note_dict['description'] and '{{ description }}' not in self.config.release_notes.entry_template:
                    lines.append(f"  {note_dict['description'][:200]}...")
                    lines.append("")

            lines.append("")

        return "\n".join(lines)


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
