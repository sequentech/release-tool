from pathlib import Path
import click
from rich.console import Console

console = Console()


@click.command('init-config', context_settings={'help_option_names': ['-h', '--help']})
@click.option('-y', '--assume-yes', is_flag=True, help='Assume "yes" for confirmation prompts')
@click.pass_context
def init_config(ctx, assume_yes: bool):
    """Create an example configuration file."""
    # Load template from config_template.toml
    # Path is relative to this file (commands/init_config.py), so go up two levels
    template_path = Path(__file__).parent.parent / "config_template.toml"
    try:
        example_config = template_path.read_text(encoding='utf-8')
    except Exception as e:
        console.print(f"[red]Error loading config template: {e}[/red]")
        console.print("[yellow]Falling back to minimal config...[/yellow]")
        example_config = """
config_version = "1.3"

[repository]
code_repo = "sequentech/step"
ticket_repos = ["sequentech/meta"]
default_branch = "main"

[github]
api_url = "https://api.github.com"

[database]
path = "release_tool.db"

[sync]
cutoff_date = "2025-01-01"
parallel_workers = 10
clone_code_repo = true
show_progress = true

[[ticket_policy.patterns]]
order = 1
strategy = "branch_name"
pattern = "/(?P<repo>\\\\w+)-(?P<ticket>\\\\d+)"
description = "Branch name format: type/repo-123/target"

[[ticket_policy.patterns]]
order = 2
strategy = "pr_body"
pattern = "Parent issue:.*?/issues/(?P<ticket>\\\\d+)"
description = "Parent issue URL in PR description"

[[ticket_policy.patterns]]
order = 3
strategy = "pr_title"
pattern = "#(?P<ticket>\\\\d+)"
description = "GitHub issue reference (#123) in PR title"

[ticket_policy]
no_ticket_action = "warn"
unclosed_ticket_action = "warn"
consolidation_enabled = true
description_section_regex = "(?:## Description|## Summary)\\\\n(.*?)(?=\\\\n##|\\\\Z)"
migration_section_regex = "(?:## Migration|## Migration Notes)\\\\n(.*?)(?=\\\\n##|\\\\Z)"

[version_policy]
gap_detection = "warn"
tag_prefix = "v"

[branch_policy]
release_branch_template = "release/{major}.{minor}"
default_branch = "main"
create_branches = true
branch_from_previous_release = true

[[release_notes.categories]]
name = "💥 Breaking Changes"
labels = ["breaking-change", "breaking"]
order = 1
alias = "breaking"

[[release_notes.categories]]
name = "🚀 Features"
labels = ["feature", "enhancement", "feat"]
order = 2
alias = "features"

[[release_notes.categories]]
name = "🛠 Bug Fixes"
labels = ["bug", "fix", "bugfix", "hotfix"]
order = 3
alias = "bugfixes"

[[release_notes.categories]]
name = "Other Changes"
labels = []
order = 99
alias = "other"

[release_notes]
excluded_labels = ["skip-changelog", "internal", "wip", "do-not-merge"]
title_template = "Release {{ version }}"
entry_template = '''- {{ title }}
  {% if url %}{{ url }}{% endif %}
  {% if authors %}
  by {% for author in authors %}{{ author.mention }}{% if not loop.last %}, {% endif %}{% endfor %}
  {% endif %}'''
output_template = '''# {{ title }}

{% set breaking_with_desc = all_notes|selectattr('category', 'equalto', '💥 Breaking Changes')|selectattr('description')|list %}
{% if breaking_with_desc|length > 0 %}
## 💥 Breaking Changes
{% for note in breaking_with_desc %}
### {{ note.title }}
{{ note.description }}
{% if note.url %}See [#{{ note.pr_numbers[0] }}]({{ note.url }}) for details.{% endif %}

{% endfor %}
{% endif %}
## 📋 All Changes
{% for category in categories %}
### {{ category.name }}
{% for note in category.notes %}
{{ render_entry(note) }}
{% endfor %}

{% endfor %}'''

[output]
output_path = "docs/docusaurus/docs/releases/release-{major}.{minor}/release-{major}.{minor}.{patch}.md"
draft_output_path = ".release_tool_cache/draft-releases/{repo}/{version}.md"
assets_path = "docs/docusaurus/docs/releases/release-{major}.{minor}/assets"
download_media = false
create_github_release = false
create_pr = false

[output.pr_templates]
branch_template = "release-notes-{version}"
title_template = "Release notes for {version}"
body_template = '''Automated release notes for version {version}.

## Summary
This PR adds release notes for {version} with {num_changes} changes across {num_categories} categories.'''
pr_target_branch = "main"
"""

    config_path = Path("release_tool.toml")
    if config_path.exists():
        console.print("[yellow]Configuration file already exists at release_tool.toml[/yellow]")

        # Get flags from context (for global -y flag) and merge with local parameter
        auto = ctx.obj.get('auto', False)
        assume_yes_global = ctx.obj.get('assume_yes', False)
        assume_yes_effective = assume_yes or assume_yes_global

        # Check both flags before prompting
        if not (auto or assume_yes_effective):
            if not click.confirm("Overwrite?"):
                return

    config_path.write_text(example_config)
    console.print(f"[green]Created configuration file: {config_path}[/green]")
    console.print("\n[blue]Next steps:[/blue]")
    console.print("1. Edit release_tool.toml and set your repository")
    console.print("2. Set GITHUB_TOKEN environment variable")
    console.print("3. Run: release-tool sync")
    console.print("4. Run: release-tool generate <version> --repo-path /path/to/repo")
