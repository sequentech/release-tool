# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Main CLI for the release tool."""

import sys
import logging
from typing import Optional
import click
from rich.console import Console

from .config import load_config
from .commands.sync import sync
from .commands.generate import generate
from .commands.publish import publish
from .commands.list_releases import list_releases
from .commands.init_config import init_config
from .commands.update_config import update_config
from .commands.issues import issues

console = Console()


@click.group(context_settings={'help_option_names': ['-h', '--help']})
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    help='Path to configuration file'
)
@click.option(
    '--auto',
    is_flag=True,
    help='Run in non-interactive mode (auto-apply defaults, skip prompts)'
)
@click.option(
    '-y', '--assume-yes',
    is_flag=True,
    help='Assume "yes" for all confirmation prompts'
)
@click.option(
    '--debug',
    is_flag=True,
    help='Show detailed debug output'
)
@click.pass_context
def cli(ctx, config: Optional[str], auto: bool, assume_yes: bool, debug: bool):
    """Release tool for managing semantic versioned releases."""
    ctx.ensure_object(dict)
    ctx.obj['auto'] = auto
    ctx.obj['assume_yes'] = assume_yes
    ctx.obj['debug'] = debug
    # Don't load config for init-config and update-config commands
    if ctx.invoked_subcommand not in ['init-config', 'update-config']:
        try:
            ctx.obj['config'] = load_config(config, auto_upgrade=auto)
        except FileNotFoundError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)


# Register commands
cli.add_command(sync)
cli.add_command(generate)
cli.add_command(publish)
cli.add_command(list_releases)
cli.add_command(init_config)
cli.add_command(update_config)
cli.add_command(issues)


def main():
    # Suppress PyGithub 403 logging for /user endpoint
    # The 403 error is expected when GITHUB_TOKEN lacks user:read scope
    # We handle this gracefully in get_authenticated_user() with a warning
    class SupressUserEndpoint403Filter(logging.Filter):
        def filter(self, record):
            # Suppress "Request GET /user failed with 403: Forbidden" messages
            if '403' in record.getMessage() and '/user' in record.getMessage():
                return False
            return True

    # Apply filter to github module loggers
    for logger_name in ['github', 'github.Requester']:
        logger = logging.getLogger(logger_name)
        logger.addFilter(SupressUserEndpoint403Filter())

    cli(obj={})


if __name__ == "__main__":
    main()
