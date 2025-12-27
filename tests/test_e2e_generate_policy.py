# SPDX-FileCopyrightText: 2025 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: MIT

"""End-to-end tests for generate command with release_version_policy."""

import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch

from release_tool.commands.generate import generate
from release_tool.config import Config
from helpers.config_helpers import create_test_config, default_pr_code_template, create_pr_code_template
from helpers.git_helpers import parse_markdown_output


class TestE2EGeneratePolicyFinalOnly:
    """
    End-to-end tests for final-only policy behavior.

    Scenario:
    - v1.0.0 (final) with PRs #101, #102
    - v1.1.0-rc.1 with PRs #103, #104
    - v1.1.0-rc.2 with PRs #105, #106
    - v1.1.0-rc.3 with PRs #107, #108
    - Generating v1.1.0-rc.4 with PRs #109, #110

    Expected behavior with final-only policy:
    - pr_code output: Contains ALL 8 PRs (#103-110) since v1.0.0 (previous final)
    - draft output: Contains only 2 PRs (#109-110) since v1.1.0-rc.3 (previous RC)
    """

    def test_final_only_rc4_shows_all_changes_since_final(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that final-only policy for RC.4 shows all changes since previous final version.

        This is the key test validating the fix.
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create config with pr_code template using final-only policy
        pr_code_template = default_pr_code_template(
            output_path=str(tmp_path / "releases" / "{{version}}.md"),
            release_version_policy="final-only"
        )

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=str(tmp_path / "draft" / "{{version}}.md"),
            # Point to the test database
            database={"path": db.db_path},
            # Configure branch policy to use main branch (not release branches)
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",  # Don't use release branches for tests
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

        # Read generated files
        pr_code_file = tmp_path / "releases" / "1.1.0-rc.4.md"
        draft_file = tmp_path / "draft" / "1.1.0-rc.4.md"

        assert pr_code_file.exists(), "pr_code file was not created"
        assert draft_file.exists(), "draft file was not created"

        pr_code_content = pr_code_file.read_text()
        draft_content = draft_file.read_text()

        # Debug: print actual content
        print(f"\n=== PR CODE CONTENT ===\n{pr_code_content}\n")
        print(f"\n=== DRAFT CONTENT ===\n{draft_content}\n")

        # Parse outputs
        pr_code_parsed = parse_markdown_output(pr_code_content)
        draft_parsed = parse_markdown_output(draft_content)

        # Verify pr_code output (final-only policy)
        # Should contain ALL 8 PRs since v1.0.0 (final)
        # PRs: 103, 104 (rc.1) + 105, 106 (rc.2) + 107, 108 (rc.3) + 109, 110 (rc.4)
        pr_code_pr_nums = set(pr_code_parsed['pr_numbers'])
        expected_pr_code_prs = {103, 104, 105, 106, 107, 108, 109, 110}

        assert pr_code_pr_nums == expected_pr_code_prs, \
            f"pr_code should contain all PRs since v1.0.0. Expected {expected_pr_code_prs}, got {pr_code_pr_nums}"

        assert len(pr_code_parsed['all_notes']) == 8, \
            f"pr_code should have 8 release notes, got {len(pr_code_parsed['all_notes'])}"

        # Verify draft output (include-rcs policy)
        # Should contain only 2 PRs since v1.1.0-rc.3 (previous RC)
        # PRs: 109, 110 (rc.4)
        draft_pr_nums = set(draft_parsed['pr_numbers'])
        expected_draft_prs = {109, 110}

        assert draft_pr_nums == expected_draft_prs, \
            f"draft should contain only PRs since v1.1.0-rc.3. Expected {expected_draft_prs}, got {draft_pr_nums}"

        assert len(draft_parsed['all_notes']) == 2, \
            f"draft should have 2 release notes, got {len(draft_parsed['all_notes'])}"

        # Verify different content
        assert pr_code_content != draft_content, \
            "pr_code and draft should have different content"

        # Verify version appears in pr_code title
        assert pr_code_parsed['title'] and "1.1.0-rc.4" in pr_code_parsed['title']

    def test_include_rcs_policy_rc4_shows_changes_since_rc3(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test that include-rcs policy for RC.4 shows only changes since RC.3.

        This verifies the include-rcs policy works correctly.
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create config with pr_code template using include-rcs policy
        pr_code_template = default_pr_code_template(
            output_path=str(tmp_path / "releases" / "{{version}}.md"),
            release_version_policy="include-rcs"  # Different policy
        )

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=str(tmp_path / "draft" / "{{version}}.md"),
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
        pr_code_file = tmp_path / "releases" / "1.1.0-rc.4.md"
        assert pr_code_file.exists()

        pr_code_content = pr_code_file.read_text()
        pr_code_parsed = parse_markdown_output(pr_code_content)

        # Verify pr_code output (include-rcs policy)
        # Should contain only 2 PRs since v1.1.0-rc.3 (previous RC)
        pr_code_pr_nums = set(pr_code_parsed['pr_numbers'])
        expected_prs = {109, 110}

        assert pr_code_pr_nums == expected_prs, \
            f"pr_code with include-rcs should contain only PRs since rc.3. Expected {expected_prs}, got {pr_code_pr_nums}"

        assert len(pr_code_parsed['all_notes']) == 2

    def test_multiple_templates_different_policies(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test multiple pr_code templates each using their own policy.

        Verifies that each template independently uses its configured policy.
        """
        # Setup: Create git history
        scenario_data = git_scenario.create_release_scenario_rc_sequence()
        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create two templates with different policies
        template_final_only = default_pr_code_template(
            output_path=str(tmp_path / "final_only" / "{{version}}.md"),
            release_version_policy="final-only"
        )

        template_include_rcs = default_pr_code_template(
            output_path=str(tmp_path / "include_rcs" / "{{version}}.md"),
            release_version_policy="include-rcs"
        )

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[template_final_only, template_include_rcs],
            draft_output_path=str(tmp_path / "draft" / "{{version}}.md"),
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

        # Read both template outputs
        final_only_file = tmp_path / "final_only" / "1.1.0-rc.4.md"
        include_rcs_file = tmp_path / "include_rcs" / "1.1.0-rc.4.md"
        draft_file = tmp_path / "draft" / "1.1.0-rc.4.md"

        assert final_only_file.exists()
        assert include_rcs_file.exists()
        assert draft_file.exists()

        final_only_parsed = parse_markdown_output(final_only_file.read_text())
        include_rcs_parsed = parse_markdown_output(include_rcs_file.read_text())
        draft_parsed = parse_markdown_output(draft_file.read_text())

        # Verify final-only template has all 8 PRs
        assert set(final_only_parsed['pr_numbers']) == {103, 104, 105, 106, 107, 108, 109, 110}
        assert len(final_only_parsed['all_notes']) == 8

        # Verify include-rcs template has only 2 PRs
        assert set(include_rcs_parsed['pr_numbers']) == {109, 110}
        assert len(include_rcs_parsed['all_notes']) == 2

        # Verify draft has only 2 PRs (uses include-rcs)
        assert set(draft_parsed['pr_numbers']) == {109, 110}
        assert len(draft_parsed['all_notes']) == 2

        # Verify templates generated different content
        assert final_only_file.read_text() != include_rcs_file.read_text()

    def test_final_version_with_final_only_policy(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test final version (1.1.0) with final-only policy.

        Final versions should also compare to previous final version.
        """
        # Setup: Create git history and tag final version
        scenario_data = git_scenario.create_release_scenario_rc_sequence()

        # Tag current HEAD as v1.1.0 (final)
        git_scenario.add_tag("v1.1.0")

        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create config
        pr_code_template = default_pr_code_template(
            output_path=str(tmp_path / "releases" / "{{version}}.md"),
            release_version_policy="final-only"
        )

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            draft_output_path=str(tmp_path / "draft" / "{{version}}.md"),
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate command for v1.1.0
        runner = CliRunner()

        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0, f"Generate failed: {result.output}"

        # Read generated file
        pr_code_file = tmp_path / "releases" / "1.1.0.md"
        assert pr_code_file.exists()

        pr_code_parsed = parse_markdown_output(pr_code_file.read_text())

        # Final version should also compare to previous final (v1.0.0)
        # Should have all 8 PRs from rc.1-rc.4
        assert set(pr_code_parsed['pr_numbers']) == {103, 104, 105, 106, 107, 108, 109, 110}
        assert len(pr_code_parsed['all_notes']) == 8


class TestE2EGenerateEdgeCases:
    """Test edge cases for generate command."""

    def test_first_rc_with_final_only_policy(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test first RC (no previous RCs) with final-only policy.

        Should compare to previous final version.
        """
        # Setup: Simpler scenario with just v1.0.0 and v1.1.0-rc.1
        git_scenario.add_commit("Initial commit")
        git_scenario.add_commit("Add feature 1", pr_number=101)
        git_scenario.add_commit("Add feature 2", pr_number=102)
        git_scenario.add_tag("v1.0.0")
        git_scenario.advance_time(days=7)

        # Add commits for rc.1
        git_scenario.add_commit("Add new feature", pr_number=103)
        git_scenario.add_commit("Add another feature", pr_number=104)

        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create config
        pr_code_template = default_pr_code_template(
            output_path=str(tmp_path / "releases" / "{{version}}.md"),
            release_version_policy="final-only"
        )

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate
        runner = CliRunner()

        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.1.0-rc.1', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0

        # Verify output
        pr_code_file = tmp_path / "releases" / "1.1.0-rc.1.md"
        pr_code_parsed = parse_markdown_output(pr_code_file.read_text())

        # Should have 2 PRs from rc.1
        assert set(pr_code_parsed['pr_numbers']) == {103, 104}
        assert len(pr_code_parsed['all_notes']) == 2

    def test_no_previous_versions(
        self, git_scenario, populated_db, mock_github_api, tmp_path
    ):
        """
        Test first version ever (no previous versions).

        Should include all commits.
        """
        # Setup: Just one RC with no previous versions
        git_scenario.add_commit("Initial commit")
        git_scenario.add_commit("Add feature 1", pr_number=101)
        git_scenario.add_commit("Add feature 2", pr_number=102)

        repo_path = Path(git_scenario.repo.working_dir)
        db, repo_id, test_data = populated_db

        # Create config
        pr_code_template = default_pr_code_template(
            output_path=str(tmp_path / "releases" / "{{version}}.md"),
            release_version_policy="final-only"
        )

        config_dict = create_test_config(
            code_repo="test/repo",
            pr_code_templates=[pr_code_template],
            database={"path": db.db_path},
            branch_policy={
                "create_branches": False,
                "default_branch": "main",
                "release_branch_template": "main",
                "branch_from_previous_release": False
            }
        )

        config = Config.from_dict(config_dict)

        # Run generate
        runner = CliRunner()

        with patch('release_tool.commands.generate.GitHubClient'):
            result = runner.invoke(
                generate,
                ['1.0.0-rc.1', '--repo-path', str(repo_path)],
                obj={'config': config, 'debug': False},
                catch_exceptions=False
            )

        assert result.exit_code == 0

        # Verify output includes all commits
        pr_code_file = tmp_path / "releases" / "1.0.0-rc.1.md"
        pr_code_parsed = parse_markdown_output(pr_code_file.read_text())

        assert set(pr_code_parsed['pr_numbers']) == {101, 102}
