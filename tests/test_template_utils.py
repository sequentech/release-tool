# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""Tests for template utilities."""

import pytest
from release_tool.template_utils import (
    render_template,
    validate_template_vars,
    get_template_variables,
    build_repo_context,
    TemplateError
)
from release_tool.config import Config, RepositoryConfig, RepoInfo
from unittest.mock import MagicMock


def test_render_template_simple():
    """Test basic template rendering."""
    template = "Version {{version}}"
    context = {'version': '1.2.3'}
    result = render_template(template, context)
    assert result == "Version 1.2.3"


def test_render_template_multiple_variables():
    """Test template with multiple variables."""
    template = "Release {{version}} ({{major}}.{{minor}}.{{patch}})"
    context = {'version': '1.2.3', 'major': '1', 'minor': '2', 'patch': '3'}
    result = render_template(template, context)
    assert result == "Release 1.2.3 (1.2.3)"


def test_render_template_multiline():
    """Test multiline template rendering."""
    template = """Parent issue: {{issue_link}}

Automated release notes for version {{version}}.

## Summary
This PR adds release notes for {{version}} with {{num_changes}} changes."""

    context = {
        'issue_link': 'https://github.com/owner/repo/issues/123',
        'version': '1.0.0',
        'num_changes': 5
    }
    result = render_template(template, context)
    assert "Parent issue: https://github.com/owner/repo/issues/123" in result
    assert "version 1.0.0" in result
    assert "with 5 changes" in result


def test_render_template_undefined_variable():
    """Test that undefined variables raise TemplateError."""
    template = "Version {{version}} by {{author}}"
    context = {'version': '1.2.3'}  # Missing 'author'

    with pytest.raises(TemplateError) as exc_info:
        render_template(template, context)
    assert "undefined" in str(exc_info.value).lower()


def test_render_template_invalid_syntax():
    """Test that invalid template syntax raises TemplateError."""
    template = "Version {{version"  # Missing closing braces
    context = {'version': '1.2.3'}

    with pytest.raises(TemplateError) as exc_info:
        render_template(template, context)
    assert "syntax" in str(exc_info.value).lower()


def test_get_template_variables():
    """Test extracting variables from template."""
    template = "Release {{version}} on {{date}} by {{author}}"
    variables = get_template_variables(template)
    assert variables == {'version', 'date', 'author'}


def test_get_template_variables_empty():
    """Test template with no variables."""
    template = "This is a static template"
    variables = get_template_variables(template)
    assert variables == set()


def test_get_template_variables_invalid_syntax():
    """Test that invalid syntax raises TemplateError."""
    template = "Release {{version"

    with pytest.raises(TemplateError):
        get_template_variables(template)


def test_validate_template_vars_success():
    """Test validation succeeds when all variables are available."""
    template = "Release {{version}} on {{date}}"
    available_vars = {'version', 'date', 'author'}

    # Should not raise
    validate_template_vars(template, available_vars, "test_template")


def test_validate_template_vars_failure():
    """Test validation fails when variables are not available."""
    template = "Release {{version}} by {{author}}"
    available_vars = {'version', 'date'}  # Missing 'author'

    with pytest.raises(TemplateError) as exc_info:
        validate_template_vars(template, available_vars, "test_template")
    assert "author" in str(exc_info.value)
    assert "undefined" in str(exc_info.value).lower()


def test_validate_template_vars_empty_template():
    """Test validation with empty template."""
    template = "Static content"
    available_vars = {'version'}

    # Should not raise
    validate_template_vars(template, available_vars, "test_template")


def test_path_template_rendering():
    """Test rendering path templates."""
    template = ".release_tool_cache/draft-releases/{{repo}}/{{version}}.md"
    context = {'repo': 'owner-repo', 'version': '1.2.3'}
    result = render_template(template, context)
    assert result == ".release_tool_cache/draft-releases/owner-repo/1.2.3.md"


def test_branch_template_rendering():
    """Test rendering branch templates."""
    template = "docs/{{repo}}-{{issue_number}}/{{target_branch}}"
    context = {
        'repo': 'sequentech/meta',
        'issue_number': '8853',
        'target_branch': 'main'
    }
    result = render_template(template, context)
    assert result == "docs/sequentech/meta-8853/main"


def test_pr_body_template():
    """Test rendering PR body template."""
    template = """Parent issue: {{issue_link}}

Automated release notes for version {{version}}.

## Summary
This PR adds release notes for {{version}} with {{num_changes}} changes across {{num_categories}} categories."""

    context = {
        'issue_link': 'https://github.com/sequentech/meta/issues/8853',
        'version': '9.2.0',
        'num_changes': 10,
        'num_categories': 3
    }
    result = render_template(template, context)
    assert "Parent issue: https://github.com/sequentech/meta/issues/8853" in result
    assert "version 9.2.0" in result
    assert "with 10 changes across 3 categories" in result


# Tests for build_repo_context

def _create_mock_config(code_repos, issue_repos=None):
    """Create a mock config with specified repos."""
    config = MagicMock()
    config.repository = MagicMock()
    config.repository.code_repos = [
        MagicMock(link=r['link'], alias=r['alias']) for r in code_repos
    ]
    config.repository.issue_repos = [
        MagicMock(link=r['link'], alias=r['alias']) for r in (issue_repos or [])
    ]
    return config


def test_build_repo_context_single_repo():
    """Test build_repo_context with a single code repo."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'}
    ])

    context = build_repo_context(config)

    # Should have code_repo with alias key
    assert 'code_repo' in context
    assert 'step' in context['code_repo']
    assert context['code_repo']['step']['link'] == 'sequentech/step'
    assert context['code_repo']['step']['slug'] == 'sequentech-step'
    assert context['code_repo']['step']['alias'] == 'step'

    # Should have code_repo_list
    assert 'code_repo_list' in context
    assert len(context['code_repo_list']) == 1
    assert context['code_repo_list'][0]['link'] == 'sequentech/step'

    # Should NOT have 'current' without current_repo_alias
    assert 'current' not in context['code_repo']


def test_build_repo_context_multiple_repos():
    """Test build_repo_context with multiple code repos."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'},
        {'link': 'sequentech/docs', 'alias': 'docs'},
        {'link': 'sequentech/api', 'alias': 'api'}
    ])

    context = build_repo_context(config)

    # Should have all repos by alias
    assert 'step' in context['code_repo']
    assert 'docs' in context['code_repo']
    assert 'api' in context['code_repo']

    # code_repo_list should have all repos
    assert len(context['code_repo_list']) == 3

    # Should NOT have 'current' without current_repo_alias
    assert 'current' not in context['code_repo']


def test_build_repo_context_with_current_alias():
    """Test build_repo_context with current_repo_alias set."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'},
        {'link': 'sequentech/docs', 'alias': 'docs'}
    ])

    context = build_repo_context(config, current_repo_alias='docs')

    # Should have 'current' pointing to docs
    assert 'current' in context['code_repo']
    assert context['code_repo']['current']['link'] == 'sequentech/docs'
    assert context['code_repo']['current']['slug'] == 'sequentech-docs'
    assert context['code_repo']['current']['alias'] == 'docs'

    # 'current' should be the same object as 'docs'
    assert context['code_repo']['current'] is context['code_repo']['docs']


def test_build_repo_context_with_invalid_current_alias():
    """Test build_repo_context with non-existent current_repo_alias."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'}
    ])

    context = build_repo_context(config, current_repo_alias='nonexistent')

    # Should NOT have 'current' when alias doesn't exist
    assert 'current' not in context['code_repo']


def test_build_repo_context_with_issue_repos():
    """Test build_repo_context includes issue repos."""
    config = _create_mock_config(
        code_repos=[{'link': 'sequentech/step', 'alias': 'step'}],
        issue_repos=[{'link': 'sequentech/meta', 'alias': 'meta'}]
    )

    context = build_repo_context(config)

    # Should have issue_repo namespace
    assert 'issue_repo' in context
    assert 'meta' in context['issue_repo']
    assert context['issue_repo']['meta']['link'] == 'sequentech/meta'
    assert context['issue_repo']['meta']['slug'] == 'sequentech-meta'

    # Should have issue_repo_list
    assert 'issue_repo_list' in context
    assert len(context['issue_repo_list']) == 1


def test_build_repo_context_template_rendering():
    """Test that build_repo_context output works with template rendering."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'}
    ])

    context = build_repo_context(config, current_repo_alias='step')
    context['version'] = '1.0.0'

    # Test template with code_repo.current
    template = ".release_tool_cache/{{code_repo.current.slug}}/{{version}}.md"
    result = render_template(template, context)
    assert result == ".release_tool_cache/sequentech-step/1.0.0.md"


def test_build_repo_context_current_raises_error_when_not_set():
    """Test that accessing code_repo.current raises error when not in context."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'}
    ])

    # No current_repo_alias provided
    context = build_repo_context(config)
    context['version'] = '1.0.0'

    # Template using code_repo.current should fail
    template = "{{code_repo.current.slug}}"
    with pytest.raises(TemplateError) as exc_info:
        render_template(template, context)
    assert "undefined" in str(exc_info.value).lower()


def test_build_repo_context_code_repo_list_iteration():
    """Test that code_repo_list can be iterated in templates."""
    config = _create_mock_config([
        {'link': 'sequentech/step', 'alias': 'step'},
        {'link': 'sequentech/docs', 'alias': 'docs'}
    ])

    context = build_repo_context(config)

    template = "{% for repo in code_repo_list %}{{ repo.alias }}{% if not loop.last %},{% endif %}{% endfor %}"
    result = render_template(template, context)
    assert result == "step,docs"
