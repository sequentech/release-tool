# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Helper functions for creating test configurations."""

import toml
from pathlib import Path
from typing import Dict, Any, List, Optional


def minimal_config(code_repo: str = "test/repo") -> Dict[str, Any]:
    """Return minimal valid configuration."""
    return {
        "repository": {
            "code_repo": code_repo
        },
        "github": {
            "token": "test_token"
        }
    }


def create_test_config(
    code_repo: str = "test/repo",
    pr_code_templates: Optional[List[Dict[str, Any]]] = None,
    draft_output_path: str = ".release_tool_cache/draft-releases/{{code_repo}}/{{version}}.md",
    **kwargs
) -> Dict[str, Any]:
    """
    Create a test configuration dictionary.

    Args:
        code_repo: Repository name
        pr_code_templates: List of pr_code template configurations
        draft_output_path: Path template for draft file
        **kwargs: Additional config overrides

    Returns:
        Configuration dictionary
    """
    config = {
        "repository": {
            "code_repo": code_repo
        },
        "github": {
            "token": "test_token"
        },
        "output": {
            "draft_output_path": draft_output_path
        }
    }

    # Add pr_code templates if provided
    if pr_code_templates:
        config["output"]["pr_code"] = {
            "templates": pr_code_templates
        }

    # Merge additional kwargs
    for key, value in kwargs.items():
        if isinstance(value, dict) and key in config:
            config[key].update(value)
        else:
            config[key] = value

    return config


def create_pr_code_template(
    output_template: str,
    output_path: str,
    release_version_policy: str = "final-only"
) -> Dict[str, Any]:
    """
    Create a pr_code template configuration.

    Args:
        output_template: Jinja2 template string for the output
        output_path: Output file path template
        release_version_policy: Policy for version comparison ("final-only" or "include-rcs")

    Returns:
        Template configuration dictionary
    """
    return {
        "output_template": output_template,
        "output_path": output_path,
        "release_version_policy": release_version_policy
    }


def default_pr_code_template(
    output_path: str = "docs/releases/{{version}}.md",
    release_version_policy: str = "final-only"
) -> Dict[str, Any]:
    """
    Create a default pr_code template with standard formatting.

    Args:
        output_path: Output file path template
        release_version_policy: Policy for version comparison

    Returns:
        Template configuration dictionary
    """
    template = """# Release {{ title }}

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
- {{ note.title }}{% if note.pr_numbers %} (#{{ note.pr_numbers[0] }}){% endif %}
{% endfor %}

{% endfor %}"""

    return create_pr_code_template(
        output_template=template,
        output_path=output_path,
        release_version_policy=release_version_policy
    )


def write_config_file(path: Path, config_dict: Dict[str, Any]) -> None:
    """
    Write configuration dictionary to TOML file.

    Args:
        path: Path to write config file
        config_dict: Configuration dictionary
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        toml.dump(config_dict, f)
