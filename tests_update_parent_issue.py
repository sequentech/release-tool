import unittest
from unittest.mock import MagicMock, patch
from github import Github, Project, Issue
from datetime import datetime, timedelta
from update_parent_issue import (get_closed_issues_in_last_n_days, get_project_by_url)


class TestGetClosedIssuesInLastNDays(unittest.TestCase):
    def setUp(self):
        self.project = MagicMock(spec=Project.Project)

    def create_mock_issue(self, state, closed_at):
        issue = MagicMock(spec=Issue.Issue)
        issue.state = state
        issue.closed_at = closed_at
        return issue

    def test_no_closed_issues(self):
        """
        Test get_closed_issues_in_last_n_days when there are no closed issues.
        """
        self.project.get_columns.return_value = []
        closed_issues = get_closed_issues_in_last_n_days(self.project, 7)
        self.assertEqual(closed_issues, [])

    def test_closed_issues_within_days(self):
        """
        Test get_closed_issues_in_last_n_days when there are closed issues within the specified days.
        """
        now = datetime.now()
        n_days_ago = now - timedelta(days=7)
        mock_closed_issue = self.create_mock_issue("closed", n_days_ago + timedelta(hours=1))

        self.project.get_columns.return_value = [
            MagicMock(get_cards=MagicMock(return_value=[
                MagicMock(
                    get_content=MagicMock(return_value=mock_closed_issue),
                    content_url="/issues/23"
                )
            ]))
        ]

        closed_issues = get_closed_issues_in_last_n_days(self.project, 7)
        self.assertEqual(closed_issues, [mock_closed_issue])

    def test_closed_issues_outside_days(self):
        """
        Test get_closed_issues_in_last_n_days when there are closed issues but they are outside the specified days.
        """
        now = datetime.now()
        n_days_ago = now - timedelta(days=7)
        mock_closed_issue = self.create_mock_issue("closed", n_days_ago - timedelta(hours=1))

        self.project.get_columns.return_value = [
            MagicMock(get_cards=MagicMock(return_value=[
                MagicMock(
                    get_content=MagicMock(return_value=mock_closed_issue),
                    content_url="/issues/367"
                )
            ]))
        ]

        closed_issues = get_closed_issues_in_last_n_days(self.project, 7)
        self.assertEqual(closed_issues, [])

    def test_mixed_closed_issues(self):
        """
        Test get_closed_issues_in_last_n_days when there are closed issues both within and outside the specified days.
        """
        now = datetime.now()
        n_days_ago = now - timedelta(days=7)
        mock_closed_issue_within = self.create_mock_issue("closed", n_days_ago + timedelta(hours=1))
        mock_closed_issue_outside = self.create_mock_issue("closed", n_days_ago - timedelta(hours=1))

        self.project.get_columns.return_value = [
            MagicMock(get_cards=MagicMock(return_value=[
                MagicMock(
                    get_content=MagicMock(return_value=mock_closed_issue_within),
                    content_url="/issues/367"
                ),
                MagicMock(
                    get_content=MagicMock(return_value=mock_closed_issue_outside),
                    content_url="/issues/368"
                ),
            ]))
        ]

        closed_issues = get_closed_issues_in_last_n_days(self.project, 7)
        self.assertEqual(closed_issues, [mock_closed_issue_within])

    def test_mixed_cards(self):
        """
        Test get_closed_issues_in_last_n_days when there are cards in the range
        but one of them is not an issue.
        """
        now = datetime.now()
        n_days_ago = now - timedelta(days=7)
        mock_closed_issue_within = self.create_mock_issue("closed", n_days_ago + timedelta(hours=1))

        self.project.get_columns.return_value = [
            MagicMock(get_cards=MagicMock(return_value=[
                MagicMock(
                    get_content=MagicMock(return_value=mock_closed_issue_within),
                    content_url="/issues/367"
                ),
                MagicMock(
                    get_content=MagicMock(return_value=mock_closed_issue_within),
                    content_url="/not-an-issue/367"
                ),
            ]))
        ]

        closed_issues = get_closed_issues_in_last_n_days(self.project, 7)
        self.assertEqual(closed_issues, [mock_closed_issue_within])


class TestGetProjectByUrl(unittest.TestCase):

    def setUp(self):
        self.github_instance = Github()
        self.org = MagicMock()
        self.project_board_url = "https://github.com/orgs/test-org/projects/123"
        self.silent = True

    @patch("update_parent_issue.re")
    def test_get_project_by_url_success(self, mock_re):
        mock_re.search.side_effect = [
            MagicMock(group=MagicMock(return_value="test-org")),
            MagicMock(group=MagicMock(return_value="123"))
        ]
        self.github_instance.get_organization = MagicMock(return_value=self.org)
        self.org.get_projects = MagicMock(return_value=[
            MagicMock(id=123, name="Project 1"),
            MagicMock(id=124, name="Project 2")
        ])

        project = get_project_by_url(self.github_instance, self.project_board_url, self.silent)
        self.assertEqual(project.id, 123)

    @patch("update_parent_issue.re")
    def test_get_project_by_url_project_not_found(self, mock_re):
        mock_re.search.side_effect = [
            MagicMock(group=MagicMock(return_value="test-org")),
            MagicMock(group=MagicMock(return_value="999"))
        ]
        self.github_instance.get_organization = MagicMock(return_value=self.org)
        self.org.get_projects = MagicMock(return_value=[
            MagicMock(id=123, name="Project 1"),
            MagicMock(id=124, name="Project 2")
        ])

        project = get_project_by_url(self.github_instance, self.project_board_url, self.silent)
        self.assertIsNone(project)

    @patch("update_parent_issue.re")
    def test_get_project_by_url_invalid_url(self, mock_re):
        mock_re.search.return_value = None

        with self.assertRaises(AttributeError):
            get_project_by_url(self.github_instance, "https://invalid_url.com", self.silent)


if __name__ == "__main__":
    unittest.main()
