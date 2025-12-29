# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""End-to-end tests for <br> tag conversion to newlines."""

import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch

from release_tool.commands.generate import generate
from release_tool.config import Config
from helpers.config_helpers import create_test_config, create_pr_code_template


class TestE2EBrTagConversion:
    """
    End-to-end tests for <br> tag conversion to newlines.

    Tests the complete flow of:
    1. Generating release notes with <br> tags in templates
    2. Verifying <br> tags convert to line breaks (not blank lines)
    3. Verifying double <br><br> creates blank lines
    4. Testing in both pr_code templates and GitHub releases
    """

    def test_br_tags_in_pr_code_template_output(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that <br> tags in pr_code templates convert to line breaks in generated files.

        Verifies:
        - Single <br> creates line break (single \\n)
        - Double <br><br> creates blank line (double \\n\\n)
        - Whitespace collapsing still works
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create pr_code template with <br> tags
        pr_code_template = create_pr_code_template(
            output_template="""# Release {{ title }}

Section One<br>Section Two<br>Section Three

Paragraph one<br><br>Paragraph two

{% for category in categories %}
## {{ category.name }}
{% for note in category.notes %}
- {{ note.title }}<br>  PR: #{{ note.pr_numbers[0] if note.pr_numbers else 'N/A' }}
{% endfor %}
{% endfor %}""",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        draft_output_path = str(tmp_path / "drafts" / "{{code_repo}}" / "{{version}}-{{output_file_type}}.md")

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=draft_output_path,
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate command
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Read generated pr_code file
        code_file = tmp_path / "drafts" / "test-repo" / "1.1.0-rc.4-code-0.md"
        assert code_file.exists(), f"PR code file not found at {code_file}"

        content = code_file.read_text()

        # Verify single <br> creates line breaks (not blank lines)
        assert "Section One\nSection Two\nSection Three" in content, \
            "Single <br> should create line breaks (\\n), not blank lines (\\n\\n)"

        # Verify double <br><br> creates blank lines
        assert "Paragraph one\n\nParagraph two" in content, \
            "Double <br><br> should create blank line (\\n\\n)"

        # Verify <br> in entry templates works
        # Look for any PR title followed by line break and PR number
        assert "PR:" in content
        # Verify that title and PR are on separate lines
        lines = content.split('\n')
        found_br_in_entry = False
        for i, line in enumerate(lines):
            if line.strip().startswith('-') and i + 1 < len(lines):
                next_line = lines[i + 1]
                if 'PR:' in next_line:
                    found_br_in_entry = True
                    break
        assert found_br_in_entry, "Entry template <br> should create line break"

    def test_br_tags_in_github_release_draft(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that <br> tags in GitHub release drafts convert to line breaks.

        Verifies:
        - <br> works in entry_template for GitHub releases
        - Single <br> creates line break
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        draft_output_path = str(tmp_path / "drafts" / "{{code_repo}}" / "{{version}}-{{output_file_type}}.md")

        # Need to configure at least one pr_code template for draft file generation
        pr_code_template = create_pr_code_template(
            output_template="# {{ title }}",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        # Configure with custom entry_template using <br>
        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=draft_output_path,
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        # Add custom entry template with <br> for GitHub release
        config_dict["release_notes"] = {
            "entry_template": "- **{{ title }}**<br>by {{ authors[0].mention if authors else 'Unknown' }}"
        }

        config = Config.from_dict(config_dict)

        # Run generate command
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Read generated GitHub release draft
        release_file = tmp_path / "drafts" / "test-repo" / "1.1.0-rc.4-release.md"
        assert release_file.exists(), f"Release file not found at {release_file}"

        content = release_file.read_text()

        # Verify <br> creates line breaks in entry templates
        # Look for PR titles followed by "by " on next line (author mention or name)
        lines = content.split('\n')
        found_br_entry = False
        for i, line in enumerate(lines):
            if line.strip().startswith('- **') and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith('by '):
                    found_br_entry = True
                    break

        assert found_br_entry, \
            f"Entry template <br> should create line break in GitHub release. Content:\n{content}"

    def test_br_tags_with_whitespace_collapsing(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that <br> tags work correctly with HTML-like whitespace collapsing.

        Verifies:
        - Multiple spaces collapse while <br> creates line breaks
        - &nbsp; entities are preserved
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create pr_code template with mixed whitespace and <br> tags
        pr_code_template = create_pr_code_template(
            output_template="""# {{ title }}

Multiple    spaces    should    collapse<br>But line breaks    should    work

Preserve&nbsp;&nbsp;double&nbsp;nbsp<br>With line break""",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        draft_output_path = str(tmp_path / "drafts" / "{{code_repo}}" / "{{version}}-{{output_file_type}}.md")

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=draft_output_path,
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate command
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Read generated file
        code_file = tmp_path / "drafts" / "test-repo" / "1.1.0-rc.4-code-0.md"
        content = code_file.read_text()

        # Verify spaces collapsed and <br> works
        assert "Multiple spaces should collapse\nBut line breaks should work" in content, \
            "Spaces should collapse but <br> should create line break"

        # Verify &nbsp; preserved and <br> works
        assert "Preserve  double nbsp\nWith line break" in content, \
            "&nbsp; should be preserved and <br> should create line break"

    def test_multiple_pr_code_templates_with_br_tags(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that <br> tags work correctly in multiple pr_code templates.

        Verifies:
        - Each template independently processes <br> tags
        - Both templates create correct line breaks
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create two pr_code templates with different <br> usage
        pr_code_template_0 = create_pr_code_template(
            output_template="Template 0<br>Line 2<br>Line 3",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        pr_code_template_1 = create_pr_code_template(
            output_template="Template 1<br><br>Paragraph 2",
            output_path="IGNORED.md",
            release_version_policy="include-rcs"
        )

        draft_output_path = str(tmp_path / "drafts" / "{{code_repo}}" / "{{version}}-{{output_file_type}}.md")

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template_0, pr_code_template_1],
            draft_output_path=draft_output_path,
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate command
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Read generated files
        code_0_file = tmp_path / "drafts" / "test-repo" / "1.1.0-rc.4-code-0.md"
        code_1_file = tmp_path / "drafts" / "test-repo" / "1.1.0-rc.4-code-1.md"

        assert code_0_file.exists()
        assert code_1_file.exists()

        content_0 = code_0_file.read_text()
        content_1 = code_1_file.read_text()

        # Verify template 0: single <br> creates line breaks
        assert "Template 0\nLine 2\nLine 3" in content_0

        # Verify template 1: double <br><br> creates blank line
        assert "Template 1\n\nParagraph 2" in content_1

    def test_trailing_br_creates_extra_newline(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that trailing <br> tag creates an extra newline at the end.

        Verifies:
        - "# Title<br>" has extra newline compared to "# Title"
        - Leading <br> also creates newline
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create pr_code template with trailing and leading <br>
        pr_code_template = create_pr_code_template(
            output_template="""# Title with trailing br<br>
Next section

<br># Title with leading br
Following content""",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        draft_output_path = str(tmp_path / "drafts" / "{{code_repo}}" / "{{version}}-{{output_file_type}}.md")

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=draft_output_path,
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate command
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Read generated file
        code_file = tmp_path / "drafts" / "test-repo" / "1.1.0-rc.4-code-0.md"
        content = code_file.read_text()

        # Verify trailing <br> creates extra newline
        # The title should be followed by empty string from split, creating a line break
        lines = content.split('\n')

        # Find the line with "Title with trailing br"
        found_trailing = False
        for i, line in enumerate(lines):
            if "Title with trailing br" in line and i + 1 < len(lines):
                # Next line should exist (from the <br>)
                # Then "Next section" should follow
                if i + 2 < len(lines) and "Next section" in lines[i + 2]:
                    # There should be one line between title and next section
                    found_trailing = True
                    break

        assert found_trailing, \
            f"Trailing <br> should create line break. Content:\n{content}"

        # Verify leading <br> creates newline
        assert "\n# Title with leading br" in content, \
            f"Leading <br> should create newline before title. Content:\n{content}"
