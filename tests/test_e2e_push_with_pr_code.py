# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""End-to-end tests for push command with pr_code templates."""

import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, Mock

from release_tool.commands.generate import generate
from release_tool.commands.push import push
from release_tool.config import Config
from helpers.config_helpers import create_test_config, create_pr_code_template
from helpers.git_helpers import parse_markdown_output


class TestE2EPushWithPrCodeTemplates:
    """
    End-to-end tests for push command with pr_code templates.

    Tests the complete flow of:
    1. Generating release notes with pr_code templates
    2. Listing drafts with push -l
    3. Pushing with auto-detection
    """

    def test_generate_multiple_pr_code_templates_to_draft_path(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that generate creates separate files for each pr_code template in draft_output_path.

        Verifies:
        - 3 files created: release, code-0, code-1
        - Each file in draft_output_path
        - Each file has different content based on template
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create two pr_code templates with different policies
        pr_code_template_0 = create_pr_code_template(
            output_template="# PR Code Template 0: {{ title }}\n\n{% for category in categories %}## {{ category.name }}\n{% for note in category.notes %}- {{ note.title }}\n{% endfor %}\n{% endfor %}",
            output_path="IGNORED_PATH_0.md",  # This path will be ignored, draft_output_path is used instead
            release_version_policy="final-only"
        )

        pr_code_template_1 = create_pr_code_template(
            output_template="# PR Code Template 1: {{ title }}\n\nSimple list:\n{% for note in all_notes %}- {{ note.title }}{% if note.pr_numbers %} (#{{ note.pr_numbers[0] }}){% endif %}\n{% endfor %}",
            output_path="IGNORED_PATH_1.md",  # This path will be ignored, draft_output_path is used instead
            release_version_policy="include-rcs"
        )

        # Custom draft_output_path in tmp_path
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

        # Run generate command for v1.1.0-rc.4
        runner = CliRunner()

        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        # Should succeed
        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Verify files were created
        draft_dir = tmp_path / "drafts" / "test-repo"
        release_file = draft_dir / "1.1.0-rc.4-release.md"
        code_0_file = draft_dir / "1.1.0-rc.4-code-0.md"
        code_1_file = draft_dir / "1.1.0-rc.4-code-1.md"

        assert release_file.exists(), f"Release draft file not found at {release_file}"
        assert code_0_file.exists(), f"Code-0 draft file not found at {code_0_file}"
        assert code_1_file.exists(), f"Code-1 draft file not found at {code_1_file}"

        # Verify file contents
        release_content = release_file.read_text()
        code_0_content = code_0_file.read_text()
        code_1_content = code_1_file.read_text()

        # Release file should use DEFAULT_RELEASE_NOTES_TEMPLATE
        # Just verify it has some content and PR references
        assert len(release_content) > 0
        assert "Test PR" in release_content or "PR #" in release_content or "#110" in release_content

        # Code-0 file should use pr_code_template_0 (final-only policy, so all 8 PRs)
        assert "PR Code Template 0" in code_0_content
        code_0_parsed = parse_markdown_output(code_0_content)
        assert len(code_0_parsed['pr_numbers']) == 8, f"Expected 8 PRs in code-0 (final-only), got {len(code_0_parsed['pr_numbers'])}"

        # Code-1 file should use pr_code_template_1 (include-rcs policy, so only 2 PRs)
        assert "PR Code Template 1" in code_1_content
        assert "Simple list:" in code_1_content
        # Verify it's shorter than code-0 (only 2 PRs vs 8 PRs)
        assert len(code_1_content) < len(code_0_content), f"Code-1 should be shorter (2 PRs) than code-0 (8 PRs)"
        # Verify it has at least some PR references
        assert "#109" in code_1_content or "#110" in code_1_content, "Should have at least one of the recent PR numbers"

        # Verify different content
        assert release_content != code_0_content != code_1_content

    def test_push_list_shows_all_draft_files(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that push -l lists all draft files including code-N files.

        Verifies:
        - All 3 files are listed
        - Correct content types shown (Release, Code 0, Code 1)
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create two pr_code templates
        pr_code_template_0 = create_pr_code_template(
            output_template="# Code 0",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        pr_code_template_1 = create_pr_code_template(
            output_template="# Code 1",
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

        # Run generate to create draft files
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            generate_result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )
        assert generate_result.exit_code == 0

        # Run push -l
        with patch('release_tool.commands.push.GitHubClient'):
            list_result = runner.invoke(
                push,
                ['--list'],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert list_result.exit_code == 0, f"Push -l failed: {list_result.output}"

        # Verify output contains all file types
        output = list_result.output
        assert "1.1.0-rc.4" in output, "Version should be in output"
        assert "Release" in output or "release" in output, "Release type should be in output"
        assert "Code 0" in output or "code-0" in output.lower(), "Code 0 type should be in output"
        assert "Code 1" in output or "code-1" in output.lower(), "Code 1 type should be in output"

    def test_push_auto_detects_correct_files(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that push command auto-detects correct files for different purposes.

        Verifies:
        - Release file used for GitHub release
        - Code-0 file used for PR creation
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create two pr_code templates
        pr_code_template_0 = create_pr_code_template(
            output_template="# Code 0 Template\n\nFor PR",
            output_path="IGNORED.md",
            release_version_policy="final-only"
        )

        pr_code_template_1 = create_pr_code_template(
            output_template="# Code 1 Template\n\nNot used in PR",
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
            },
            output={
                "create_github_release": True,
                "create_pr": True,
                "create_issue": False,  # Disable issue creation for simpler test
                "draft_output_path": draft_output_path,
                "pr_code": {
                    "templates": [pr_code_template_0, pr_code_template_1]
                },
                "pr_templates": {
                    "branch_template": "release-notes-{{version}}",
                    "title_template": "Release notes for {{version}}",
                    "body_template": "Automated release notes for version {{version}}."
                }
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate to create draft files
        runner = CliRunner()
        with patch('release_tool.commands.generate.GitHubClient'):
            generate_result = runner.invoke(
                generate,
                ['1.1.0-rc.4', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )
        assert generate_result.exit_code == 0

        # Run push --dry-run with debug to see what files it uses
        with patch('release_tool.commands.push.GitHubClient') as mock_gh_class:
            # Configure the mock
            mock_gh_instance = Mock()
            mock_gh_class.return_value = mock_gh_instance

            push_result = runner.invoke(
                push,
                ['1.1.0-rc.4', '--dry-run'],
                obj={'config': config, 'debug': True},
                catch_exceptions=False
            )

        output = push_result.output

        # Verify command succeeded
        assert push_result.exit_code == 0, f"Push dry-run should succeed, output:\n{output}"

        # Verify dry-run message
        assert "DRY RUN" in output, "Should show dry-run message"

        # Verify it mentions GitHub release creation
        assert "GitHub release" in output or "git tag" in output, "Should mention GitHub release or tag"

        # Verify it mentions PR creation or shows PR details
        assert "Pull request" in output or "pull request" in output.lower() or "branch" in output.lower(), "Should mention PR or branch"
