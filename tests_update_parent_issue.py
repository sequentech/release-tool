# SPDX-FileCopyrightText: 2023 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: AGPL-3.0-only
import unittest
from unittest.mock import MagicMock, patch
from github import Github, Project, Issue
from datetime import datetime, timedelta
from update_parent_issue import (get_closed_issues_in_last_n_days, get_project_id)


class TestGetClosedIssuesInLastNDays(unittest.TestCase):
    def setUp(self):
        self.project = MagicMock(spec=Project.Project)
        self.access_token = "fake_access_token"
        self.silent = True

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
        closed_issues = get_closed_issues_in_last_n_days(self.project, 7, self.access_token, self.silent)
        self.assertEqual(closed_issues, [])

    def test_closed_issues_within_days(self):
        """
        Test get_closed_issues_in_last_n_days when there are closed issues 
        within the specified days.
        """
        now = datetime.now()
        n_days_ago = now - timedelta(days=7)
        closed_at = (n_days_ago + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        mock_response = {
            "data": {
                "node": {
                    "items": {
                        "nodes": [
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "title": "Mock issue",
                                    "closedAt": closed_at,
                                    "state": "CLOSED",
                                    "body": "Mock issue body",
                                    "url": "https://github.com/mock_owner/mock_repo/issues/1",
                                    "repository": {"name": "mock_repo"},
                                    "assignees": {"nodes": [{"login": "mock_user"}]},
                                }
                            }
                        ],
                        "totalCount": 1,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

        with patch("update_parent_issue.send_graphql_query") as mock_send_graphql_query:
            mock_send_graphql_query.return_value = mock_response

            closed_issues = get_closed_issues_in_last_n_days(self.project, 7, self.access_token, self.silent)
            self.assertEqual(len(closed_issues), 1)
            self.assertEqual(closed_issues[0]["content"]["title"], "Mock issue")

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

        closed_issues = get_closed_issues_in_last_n_days(self.project, 7, self.access_token, self.silent)
        self.assertEqual(closed_issues, [])

    def test_mixed_closed_issues(self):
        """
        Test get_closed_issues_in_last_n_days when there are a mix of open and 
        closed issues within the specified days.
        """
        now = datetime.now()
        n_days_ago = now - timedelta(days=7)
        closed_at = (n_days_ago + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        mock_response = {
            "data": {
                "node": {
                    "items": {
                        "nodes": [
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "title": "Closed issue",
                                    "closedAt": closed_at,
                                    "state": "CLOSED",
                                    "body": "Closed issue body",
                                    "url": "https://github.com/mock_owner/mock_repo/issues/1",
                                    "repository": {"name": "mock_repo"},
                                    "assignees": {"nodes": [{"login": "mock_user"}]},
                                }
                            },
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "title": "Open issue",
                                    "closedAt": None,
                                    "state": "OPEN",
                                    "body": "Open issue body",
                                    "url": "https://github.com/mock_owner/mock_repo/issues/2",
                                    "repository": {"name": "mock_repo"},
                                    "assignees": {"nodes": [{"login": "mock_user"}]},
                                }
                            }
                        ],
                        "totalCount": 2,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

        with patch("update_parent_issue.send_graphql_query") as mock_send_graphql_query:
            mock_send_graphql_query.return_value = mock_response

            closed_issues = get_closed_issues_in_last_n_days(self.project, 7, self.access_token, self.silent)
            self.assertEqual(len(closed_issues), 1)
            self.assertEqual(closed_issues[0]["content"]["title"], "Closed issue")


class TestGetProjectByUrl(unittest.TestCase):

    def setUp(self):
        self.access_token = "fake_access_token"
        self.project_board_url = "https://github.com/orgs/test-org/projects/123"
        self.silent = True

    @patch("update_parent_issue.re")
    @patch("update_parent_issue.send_graphql_query")
    def test_get_project_by_url_success(self, mock_send_graphql_query, mock_re):
        mock_re.search.side_effect = [
            MagicMock(group=MagicMock(return_value="test-org")),
            MagicMock(group=MagicMock(return_value="123"))
        ]

        mock_send_graphql_query.return_value = {
            "data": {
                "organization": {
                    "projectV2": {
                        "id": 123
                    }
                }
            }
        }

        project_id = get_project_id(self.access_token, self.project_board_url, self.silent)
        self.assertEqual(project_id, 123)

    @patch("update_parent_issue.re")
    @patch("update_parent_issue.send_graphql_query")
    def test_get_project_by_url_project_not_found(self, mock_send_graphql_query, mock_re):
        mock_re.search.side_effect = [
            MagicMock(group=MagicMock(return_value="test-org")),
            MagicMock(group=MagicMock(return_value="999"))
        ]

        mock_send_graphql_query.return_value = None

        project_id = get_project_id(self.access_token, self.project_board_url, self.silent)
        self.assertIsNone(project_id)

    @patch("update_parent_issue.re")
    def test_get_project_by_url_invalid_url(self, mock_re):
        mock_re.search.return_value = None

        with self.assertRaises(AttributeError):
            get_project_id(self.access_token, "https://invalid_url.com", self.silent)


if __name__ == "__main__":
    unittest.main()
