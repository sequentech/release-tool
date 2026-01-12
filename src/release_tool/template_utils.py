# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Template rendering utilities using Jinja2."""

from typing import Dict, Set, Any, TYPE_CHECKING
from jinja2 import Template, TemplateSyntaxError, UndefinedError, StrictUndefined

if TYPE_CHECKING:
    from .config import Config


class TemplateError(Exception):
    """Exception raised for template-related errors."""
    pass


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    """
    Render a Jinja2 template with the given context.

    Args:
        template_str: Jinja2 template string using {{ variable }} syntax
        context: Dictionary of variables available to the template

    Returns:
        Rendered template string

    Raises:
        TemplateError: If template syntax is invalid or uses undefined variables
    """
    try:
        # Use StrictUndefined to raise errors for undefined variables
        template = Template(template_str, undefined=StrictUndefined)
        return template.render(**context)
    except TemplateSyntaxError as e:
        raise TemplateError(f"Invalid template syntax: {e}")
    except UndefinedError as e:
        raise TemplateError(f"Template uses undefined variable: {e}")
    except Exception as e:
        raise TemplateError(f"Template rendering error: {e}")


def validate_template_vars(
    template_str: str,
    available_vars: Set[str],
    template_name: str = "template"
) -> None:
    """
    Validate that a template only uses variables that are available.

    This function parses the template and checks that all variable references
    exist in the available_vars set. It raises an error if undefined variables are used.

    Args:
        template_str: Jinja2 template string to validate
        available_vars: Set of variable names that are available
        template_name: Name of the template for error messages

    Raises:
        TemplateError: If template uses variables not in available_vars
    """
    try:
        # Parse template to find variable references
        from jinja2 import meta, Environment
        env = Environment()
        ast = env.parse(template_str)
        referenced_vars = meta.find_undeclared_variables(ast)

        # Check if any referenced vars are not in available_vars
        undefined = referenced_vars - available_vars
        if undefined:
            raise TemplateError(
                f"{template_name} uses undefined variables: {', '.join(sorted(undefined))}. "
                f"Available variables: {', '.join(sorted(available_vars))}"
            )

    except TemplateSyntaxError as e:
        raise TemplateError(f"Invalid {template_name} syntax: {e}")
    except TemplateError:
        # Re-raise our own errors
        raise
    except Exception as e:
        # Other errors are likely bugs, but we'll wrap them
        raise TemplateError(f"Error validating {template_name}: {e}")


def get_template_variables(template_str: str) -> Set[str]:
    """
    Extract all variable names used in a template.

    Args:
        template_str: Jinja2 template string

    Returns:
        Set of variable names referenced in the template

    Raises:
        TemplateError: If template syntax is invalid
    """
    try:
        from jinja2 import meta
        template = Template(template_str)
        env = template.environment
        ast = env.parse(template_str)
        return meta.find_undeclared_variables(ast)
    except TemplateSyntaxError as e:
        raise TemplateError(f"Invalid template syntax: {e}")
    except Exception as e:
        raise TemplateError(f"Error parsing template: {e}")


def build_repo_context(config: "Config") -> Dict[str, Any]:
    """
    Build template context for repository variables.

    Creates a nested structure for accessing code repos and issue repos by alias:
    - code_repo.primary.link: Primary code repo link (e.g., 'sequentech/step')
    - code_repo.primary.slug: Primary code repo slug (e.g., 'sequentech-step')
    - code_repo.<alias>.link: Code repo link by alias
    - code_repo.<alias>.slug: Code repo slug by alias
    - issue_repo.<alias>.link: Issue repo link by alias
    - issue_repo.<alias>.slug: Issue repo slug by alias

    Args:
        config: Configuration object

    Returns:
        Dictionary with 'code_repo' and 'issue_repo' namespaces
    """
    code_repo_context = {}
    issue_repo_context = {}

    # Add primary code repo
    primary_repo = config.get_primary_code_repo()
    code_repo_context['primary'] = {
        'link': primary_repo.link,
        'slug': primary_repo.link.replace('/', '-')
    }

    # Add all code repos by alias
    for repo in config.repository.code_repos:
        code_repo_context[repo.alias] = {
            'link': repo.link,
            'slug': repo.link.replace('/', '-')
        }

    # Add all issue repos by alias
    for repo in config.repository.issue_repos:
        issue_repo_context[repo.alias] = {
            'link': repo.link,
            'slug': repo.link.replace('/', '-')
        }

    return {
        'code_repo': code_repo_context,
        'issue_repo': issue_repo_context
    }
