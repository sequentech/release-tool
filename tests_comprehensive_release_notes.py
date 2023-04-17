import unittest
from unittest.mock import MagicMock
from comprehensive_release_notes import get_comprehensive_release_notes

class TestComprehensiveReleaseNotes(unittest.TestCase):
    def test_get_comprehensive_release_notes(self):
        """
        Test that the get_comprehensive_release_notes function returns deduplicated release notes.
        """
        args = MagicMock()
        args.silent = False
        token = "dummy_token"
        repos = ["org/repo1", "org/repo2"]
        prev_release = "1.1.0"
        new_release = "1.2.0"
        config = {}

        # Mock GitHub API calls
        gh = MagicMock()
        repo1 = MagicMock()
        repo2 = MagicMock()
        gh.get_repo.side_effect = [repo1, repo2]

        repo1_notes = {
            "Feature": ["Feature 1 in repo1 (https://link1)", "Feature 2 in repo1 (https://link2)"],
            "Bugfix": ["Bugfix 1 in repo1 (https://link3)"]
        }

        repo2_notes = {
            "Feature": ["Feature 1 in repo2 (https://link4)", "Feature 1 in repo1 (https://link1)"],
            "Bugfix": ["Bugfix 1 in repo2 (https://link5)", "Bugfix 1 in repo1 (https://link3)"]
        }

        get_release_notes = MagicMock()
        get_release_notes.side_effect = [repo1_notes, repo2_notes]

        # Test get_comprehensive_release_notes
        with unittest.mock.patch("comprehensive_release_notes.Github", return_value=gh):
            with unittest.mock.patch("comprehensive_release_notes.get_release_notes", side_effect=[repo1_notes, repo2_notes]):
                release_notes = get_comprehensive_release_notes(args, token, repos, prev_release, new_release, config)

        expected_release_notes = {
            "Feature": [
                "Feature 1 in repo1 (https://link1)",
                "Feature 2 in repo1 (https://link2)",
                "Feature 1 in repo2 (https://link4)"
            ],
            "Bugfix": [
                "Bugfix 1 in repo1 (https://link3)",
                "Bugfix 1 in repo2 (https://link5)"
            ]
        }

        self.assertEqual(release_notes, expected_release_notes)

if __name__ == '__main__':
    unittest.main()
