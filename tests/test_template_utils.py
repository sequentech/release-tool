"""Tests for template utilities."""

import pytest
from release_tool.template_utils import (
    render_template,
    validate_template_vars,
    get_template_variables,
    TemplateError
)


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
