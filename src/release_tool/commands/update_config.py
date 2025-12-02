import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
import tomlkit

console = Console()


def _merge_config_with_template(user_data: dict, template_doc) -> dict:
    """Merge user config with template, preserving comments and structure.

    Args:
        user_data: User's config as plain dict (from tomli)
        template_doc: Template loaded with tomlkit (has comments)

    Returns:
        Merged tomlkit document with template comments and user values
    """
    def to_tomlkit_value(value):
        """Convert plain Python value to tomlkit type to preserve comments."""
        if isinstance(value, dict):
            result = tomlkit.table()
            for k, v in value.items():
                result[k] = to_tomlkit_value(v)
            return result
        elif isinstance(value, list):
            result = tomlkit.array()
            for item in value:
                result.append(to_tomlkit_value(item))
            return result
        else:
            # Scalars (str, int, bool, etc.) are fine as-is
            return value

    def values_equal(val1, val2):
        """Check if two values are equal for merge purposes."""
        # Convert both to comparable types
        if isinstance(val1, (list, dict)) and isinstance(val2, (list, dict)):
            # Use unwrap to get plain Python objects for comparison
            v1 = val1.unwrap() if hasattr(val1, 'unwrap') else val1
            v2 = val2.unwrap() if hasattr(val2, 'unwrap') else val2
            return v1 == v2
        else:
            # For scalars, convert to string for comparison
            return str(val1) == str(val2)

    def update_values_in_place(template_item, user_value):
        """Update template values in-place with user values."""
        if isinstance(template_item, dict) and isinstance(user_value, dict):
            # Update each key in template with user's value
            # Create list of keys first to avoid "dictionary changed during iteration"
            for key in list(template_item.keys()):
                if key in user_value:
                    template_val = template_item[key]
                    user_val = user_value[key]

                    # SKIP updating if values are identical - this preserves comments!
                    if values_equal(template_val, user_val):
                        continue

                    # Check if we need to recurse
                    if isinstance(template_val, dict) and isinstance(user_val, dict):
                        update_values_in_place(template_val, user_val)
                    # Special handling for AoT (Array of Tables) - preserve the type
                    elif isinstance(template_val, tomlkit.items.AoT) and isinstance(user_val, list):
                        # Clear existing items and repopulate with user data
                        template_val.clear()
                        for item in user_val:
                            template_val.append(to_tomlkit_value(item))
                    elif isinstance(template_val, list) and isinstance(user_val, list):
                        # For regular lists, preserve trivia and convert to tomlkit array
                        old_trivia = template_val.trivia if hasattr(template_val, 'trivia') else None
                        new_val = to_tomlkit_value(user_val)
                        if old_trivia and hasattr(new_val, 'trivia'):
                            new_val.trivia.indent = old_trivia.indent
                            new_val.trivia.comment_ws = old_trivia.comment_ws
                            new_val.trivia.comment = old_trivia.comment
                            new_val.trivia.trail = old_trivia.trail
                        template_item[key] = new_val
                    else:
                        # Primitive value - preserve trivia and convert to tomlkit type
                        old_trivia = template_val.trivia if hasattr(template_val, 'trivia') else None
                        new_val = to_tomlkit_value(user_val)
                        if old_trivia and hasattr(new_val, 'trivia'):
                            new_val.trivia.indent = old_trivia.indent
                            new_val.trivia.comment_ws = old_trivia.comment_ws
                            new_val.trivia.comment = old_trivia.comment
                            new_val.trivia.trail = old_trivia.trail
                        template_item[key] = new_val

            # Add any keys from user that template doesn't have
            for key in user_value:
                if key not in template_item:
                    template_item[key] = to_tomlkit_value(user_value[key])

    # Modify template in-place to preserve comments
    # Create list of keys first to avoid "dictionary changed during iteration"
    for key in list(template_doc.keys()):
        if key in user_data:
            template_item = template_doc[key]

            # Update values in place
            update_values_in_place(template_item, user_data[key])

    # Add any top-level keys user has that template doesn't have
    for key in user_data:
        if key not in template_doc:
            template_doc[key] = to_tomlkit_value(user_data[key])

    return template_doc


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.option(
    '--dry-run',
    is_flag=True,
    help='Show what would be upgraded without making changes'
)
@click.option(
    '--target-version',
    help='Target version to upgrade to (default: latest)'
)
@click.option(
    '--restore-comments',
    is_flag=True,
    help='Restore comments and reformat templates (works on same version)'
)
@click.option('-y', '--assume-yes', is_flag=True, help='Assume "yes" for confirmation prompts')
@click.pass_context
def update_config(ctx, dry_run: bool, target_version: Optional[str], restore_comments: bool, assume_yes: bool):
    """Update configuration file to the latest version.

    This command upgrades your release_tool.toml configuration file to the
    latest format version, applying any necessary migrations.
    """
    from ..migrations import MigrationManager

    # Determine config file path
    config_path = ctx.parent.params.get('config') if ctx.parent else None
    if not config_path:
        # Look for default config files
        default_paths = [
            "release_tool.toml",
            ".release_tool.toml",
            "config/release_tool.toml"
        ]
        for path in default_paths:
            if Path(path).exists():
                config_path = path
                break

    if not config_path:
        console.print("[red]Error: No configuration file found[/red]")
        console.print("Please specify a config file with --config or create one using:")
        console.print("  release-tool init-config")
        sys.exit(1)

    config_path = Path(config_path)
    console.print(f"[blue]Checking configuration file: {config_path}[/blue]\n")

    # Load current config (use tomlkit to preserve comments)
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = tomlkit.load(f)
    except Exception as e:
        console.print(f"[red]Error reading config file: {e}[/red]")
        sys.exit(1)

    # Check version first to determine if we need to merge with template
    manager = MigrationManager()
    current_version = data.get('config_version', '1.0')
    target_ver = target_version or manager.CURRENT_VERSION

    # Always load template and merge to preserve comments during upgrades
    # This ensures user's values are kept but template comments are restored
    if manager.needs_upgrade(current_version) or restore_comments:
        try:
            template_path = Path(__file__).parent.parent / "config_template.toml"
            with open(template_path, 'r', encoding='utf-8') as f:
                template_doc = tomlkit.load(f)

            # Merge: use template structure/comments but user's values
            data = _merge_config_with_template(data, template_doc)
            console.print("[dim]✓ Loaded comments from template[/dim]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load template comments: {e}[/yellow]")
            # Continue without comments - not critical

    console.print(f"Current version: [yellow]{current_version}[/yellow]")
    console.print(f"Target version:  [green]{target_ver}[/green]\n")

    # Check if upgrade is needed (unless restoring comments)
    if not manager.needs_upgrade(current_version) and not restore_comments:
        console.print("[green]✓ Configuration is already up to date![/green]")
        return

    # If restoring comments on same version, show different message
    if restore_comments and current_version == target_ver:
        console.print("[blue]Restoring comments and reformatting templates...[/blue]\n")
    else:
        # Show changes
        changes = manager.get_changes_description(current_version, target_ver)
        console.print("[blue]Changes:[/blue]")
        console.print(changes)
        console.print()

    if dry_run:
        console.print("[yellow]Dry-run mode: No changes made[/yellow]")
        return

    # Get flags from context (for global -y flag) and merge with local parameter
    auto = ctx.obj.get('auto', False)
    assume_yes_global = ctx.obj.get('assume_yes', False)
    assume_yes_effective = assume_yes or assume_yes_global

    # Confirm upgrade
    if not (auto or assume_yes_effective):
        if not click.confirm(f"Upgrade config from v{current_version} to v{target_ver}?"):
            console.print("[yellow]Upgrade cancelled[/yellow]")
            return

    # Apply migrations
    try:
        console.print(f"[blue]Upgrading configuration...[/blue]")

        # If restoring comments on same version, force run current version migration
        if restore_comments and current_version == target_ver:
            # For v1.1, reapply the v1.0 -> v1.1 migration to reformat templates
            if current_version == "1.1":
                from ..migrations.v1_0_to_v1_1 import migrate as v1_1_migrate
                upgraded_data = v1_1_migrate(data)
            else:
                # For other versions, just use the data as-is
                upgraded_data = data
        else:
            # Normal upgrade path
            upgraded_data = manager.upgrade_config(data, target_ver)

        # Save back to file
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(tomlkit.dumps(upgraded_data))

        console.print(f"[green]✓ Configuration upgraded to v{target_ver}![/green]")
        console.print(f"[green]✓ Saved to {config_path}[/green]")

    except Exception as e:
        console.print(f"[red]Error during upgrade: {e}[/red]")
        sys.exit(1)
