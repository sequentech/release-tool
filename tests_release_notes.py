# SPDX-FileCopyrightText: 2023 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: AGPL-3.0-only

import unittest
from unittest.mock import MagicMock, Mock
from github import Repository
from release_notes import (
    get_label_category, get_release_notes, create_release_notes_md
)

class TestGetReleaseNotes(unittest.TestCase):
    def generate_labels(self, labels):
        ret = []
        for label in labels:
            mock = Mock(name=label)
            mock.name = label
            ret.append(mock)
        return ret

    def setUp(self):
        self.repo = MagicMock(spec=Repository.Repository)
        self.repo.compare.return_value.commits = []
        self.config = {
            "changelog": {
                "exclude": {"labels": ["skip-changelog"]},
                "categories": [
                    {"title": "Bug Fixes", "labels": ["bug"]},
                    {"title": "New Features", "labels": ["enhancement"]}
                ]
            }
        }

    def test_get_release_notes_empty(self):
        release_notes = get_release_notes(self.repo, "1.0.0", "1.1.0", self.config)
        self.assertEqual(release_notes, {})

    def test_get_release_notes_with_data(self):
        commit = Mock()
        pr = Mock()
        pr.labels = self.generate_labels(["bug"])
        pr.title = "Fix a bug"
        pr.user.login = "user"
        pr.html_url = "https://github.com/username/repo/pull/1"
        pr.body = ""
        commit.get_pulls.return_value = Mock(totalCount=1, __getitem__=lambda s, i: pr)
        self.repo.compare.return_value.commits = [commit]

        expected_release_notes = {
            "Bug Fixes": [
                "* Fix a bug by @user in https://github.com/username/repo/pull/1"
            ]
        }
        release_notes = get_release_notes(self.repo, "1.0.0", "1.1.0", self.config)
        self.assertEqual(release_notes, expected_release_notes)

    def test_get_release_notes_with_excluded_label(self):
        commit = Mock()
        pr = Mock()
        pr.labels = self.generate_labels(["skip-changelog"])
        pr.title = "Fix a bug"
        pr.user.login = "user"
        pr.html_url = "https://github.com/username/repo/pull/1"
        pr.body = ""
        commit.get_pulls.return_value = Mock(totalCount=1, __getitem__=lambda s, i: pr)
        self.repo.compare.return_value.commits = [commit]

        release_notes = get_release_notes(self.repo, "1.0.0", "master", self.config)
        self.assertEqual(release_notes, {})

    def test_get_release_notes_with_parent_issue(self):
        commit = Mock()
        pr = Mock()
        pr.labels = self.generate_labels(["bug"])
        pr.title = "Fix a bug"
        pr.user.login = "user"
        pr.html_url = "https://github.com/username/repo/pull/1"
        pr.body = "Parent issue: https://github.com/username/repo/issues/1"
        commit.get_pulls.return_value = Mock(totalCount=1, __getitem__=lambda s, i: pr)
        self.repo.compare.return_value.commits = [commit]

        expected_release_notes = {
            "Bug Fixes": [
                "* Fix a bug by @user in https://github.com/username/repo/issues/1"
            ]
        }
        release_notes = get_release_notes(self.repo, "1.0.0", "1.1.0", self.config)
        self.assertEqual(release_notes, expected_release_notes)

    def test_get_release_notes_with_parent_issue_already_included(self):
        commit = Mock()
        pr = Mock()
        pr.labels = self.generate_labels(["bug"])
        pr.title = "Fix a bug"
        pr.user.login = "user"
        pr.html_url = "https://github.com/username/repo/pull/1"
        pr.body = "Parent issue: https://github.com/username/repo/issues/1"
        commit.get_pulls.return_value = Mock(totalCount=1, __getitem__=lambda s, i: pr)
        self.repo.compare.return_value.commits = [commit, commit]

        expected_release_notes = {
            "Bug Fixes": [
                "* Fix a bug by @user in https://github.com/username/repo/issues/1"
            ]
        }
        release_notes = get_release_notes(self.repo, "1.0.0", "1.1.0", self.config)
        self.assertEqual(release_notes, expected_release_notes)

    def test_get_release_notes_with_no_matching_category(self):
        commit = Mock()
        pr = Mock()
        pr.labels = self.generate_labels(["other"])
        pr.title = "Other change"
        pr.user.login = "user"
        pr.html_url = "https://github.com/username/repo/pull/1"
        pr.body = ""
        commit.get_pulls.return_value = Mock(totalCount=1, __getitem__=lambda s, i: pr)
        self.repo.compare.return_value.commits = [commit]

        release_notes = get_release_notes(self.repo, "1.0.0", "1.1.0", self.config)
        self.assertEqual(release_notes, {})

    def test_get_release_notes_with_wildcard_category(self):
        self.config["changelog"]["categories"].append(
            {"title": "Other Changes", "labels": ["*"]}
        )
        commit = Mock()
        pr = Mock()
        pr.labels = self.generate_labels(["other"])
        pr.title = "Other change"
        pr.user.login = "user"
        pr.html_url = "https://github.com/username/repo/pull/1"
        pr.body = ""
        commit.get_pulls.return_value = Mock(totalCount=1, __getitem__=lambda s, i: pr)
        self.repo.compare.return_value.commits = [commit]

        expected_release_notes = {
            "Other Changes": [
                "* Other change by @user in https://github.com/username/repo/pull/1"
            ]
        }
        release_notes = get_release_notes(self.repo, "1.0.0", "1.1.0", self.config)
        self.assertEqual(release_notes, expected_release_notes)


class TestGetLabelCategory(unittest.TestCase):
    def generate_labels(self, labels):
        ret = []
        for label in labels:
            mock = Mock(name=label)
            mock.name = label
            ret.append(mock)
        return ret


    def test_no_matching_labels(self):
        labels = self.generate_labels(["bugfix", "documentation"])
        categories = [
            {"labels": ["enhancement"], "title": "Enhancements"},
            {"labels": ["security"], "title": "Security"}
        ]
        result = get_label_category(labels, categories)
        self.assertIsNone(result)

    def test_single_matching_label(self):
        labels = self.generate_labels(["bugfix", "documentation"])
        categories = [
            {"labels": ["bugfix"], "title": "Bug Fixes"},
            {"labels": ["security"], "title": "Security"}
        ]
        expected = {"labels": ["bugfix"], "title": "Bug Fixes"}
        result = get_label_category(labels, categories)
        self.assertEqual(result, expected)

    def test_multiple_matching_labels(self):
        labels = self.generate_labels(["bugfix", "documentation"])
        categories = [
            {"labels": ["bugfix"], "title": "Bug Fixes"},
            {"labels": ["documentation"], "title": "Documentation"}
        ]
        expected = {"labels": ["bugfix"], "title": "Bug Fixes"}
        result = get_label_category(labels, categories)
        self.assertEqual(result, expected)

    def test_wildcard_matching_label(self):
        labels = self.generate_labels(["bugfix", "documentation"])
        categories = [
            {"labels": ["*"], "title": "All"},
            {"labels": ["security"], "title": "Security"}
        ]
        expected = {"labels": ["*"], "title": "All"}
        result = get_label_category(labels, categories)
        self.assertEqual(result, expected)

    def test_wildcard_matching_label_with_other_labels(self):
        labels = self.generate_labels(["bugfix", "documentation"])
        categories = [
            {"labels": ["*", "security"], "title": "All and Security"},
            {"labels": ["enhancement"], "title": "Enhancements"}
        ]
        expected = {"labels": ["*", "security"], "title": "All and Security"}
        result = get_label_category(labels, categories)
        self.assertEqual(result, expected)


class TestCreateReleaseNotesMd(unittest.TestCase):
    def test_create_release_notes_md(self):
        release_notes = {
            "Bug Fixes": [
                "* Fix a bug by @user in https://github.com/username/repo/pull/1"
            ],
            "New Features": [
                "* Add a new feature by @user2 in https://github.com/username/repo/pull/2"
            ]
        }
        new_release = "1.1.0"
        expected_md = """<!-- Release notes generated using configuration in .github/release.yml at 1.1.0 -->

## What's Changed
### Bug Fixes
* Fix a bug by @user in https://github.com/username/repo/pull/1
### New Features
* Add a new feature by @user2 in https://github.com/username/repo/pull/2
"""
        md = create_release_notes_md(release_notes, new_release)
        self.assertEqual(md, expected_md)

if __name__ == '__main__':
    unittest.main()