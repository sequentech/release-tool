import unittest
from unittest.mock import patch, MagicMock
from comprehensive_release_notes import (
    parse_arguments,
    get_comprehensive_release_notes,
    main
)

class TestComprehensiveReleaseNotes(unittest.TestCase):
    def test_get_comprehensive_release_notes(self):
        """
        Test that the get_comprehensive_release_notes function returns deduplicated release notes.
        """
        args = MagicMock()
        args.silent = True
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
            "Feature": ["Feature 1 in repo2 (https://link4)", "Feature 1 in repo2 (https://link1)"],
            "Bugfix": ["Bugfix 2 in repo2 (https://link5)", "Bugfix 1 in repo2 (https://link3)"]
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
                "Bugfix 2 in repo2 (https://link5)"
            ]
        }

        self.assertEqual(release_notes, expected_release_notes)


class TestMainComprehensiveReleaseNotes(unittest.TestCase):
    """
    Test cases for comprehensive_release_notes.py
    """

    def test_parse_arguments(self):
        """
        Test that parse_arguments() correctly parses the command line arguments.
        """
        with patch('argparse.ArgumentParser.parse_args') as mock_args:
            mock_args.return_value = MagicMock(
                previous_release='1.1',
                new_release='1.2.0',
                dry_run=True,
                silent=True
            )

            args = parse_arguments()

            self.assertEqual(args.previous_release, '1.1')
            self.assertEqual(args.new_release, '1.2.0')
            self.assertTrue(args.dry_run)
            self.assertTrue(args.silent)

    @patch('comprehensive_release_notes.get_release_notes')
    @patch('comprehensive_release_notes.Github')
    def test_get_comprehensive_release_notes(self, mock_github, mock_get_release_notes):
        """
        Test that get_comprehensive_release_notes() correctly generates and deduplicates release notes.
        """
        mock_args = MagicMock(silent=True)
        token = "test_token"
        repos = ["org/repo1", "org/repo2"]
        prev_release = "1.1.0"
        new_release = "1.2.0"
        config = {}

        mock_get_release_notes.side_effect = [
            {
                "Feature": ["Feature 1 in repo1 (https://link1)", "Feature 2 in repo1 (https://link2)"],
                "Bugfix": ["Bugfix 1 in repo1 (https://link3)"]
            },
            {
                "Feature": ["Feature 1 in repo2 (https://link4)", "Feature 1 in repo2 (https://link1)"],
                "Bugfix": ["Bugfix 2 in repo2 (https://link5)", "Bugfix 1 in repo2 (https://link3)"]
            }
        ]

        release_notes = get_comprehensive_release_notes(mock_args, token, repos, prev_release, new_release, config)

        self.assertEqual(release_notes, {
            "Feature": [
                "Feature 1 in repo1 (https://link1)",
                "Feature 2 in repo1 (https://link2)",
                "Feature 1 in repo2 (https://link4)"
            ],
            "Bugfix": [
                "Bugfix 1 in repo1 (https://link3)",
                "Bugfix 2 in repo2 (https://link5)"
            ]
        })

    @patch('comprehensive_release_notes.parse_arguments')
    @patch('comprehensive_release_notes.get_comprehensive_release_notes')
    @patch('comprehensive_release_notes.create_release_notes_md')
    @patch('comprehensive_release_notes.Github')
    def test_main(self, mock_github, mock_create_release_notes_md, mock_get_comprehensive_release_notes, mock_parse_arguments):
        """
        Test the main() function with proper execution and handling of dry_run flag.
        """
        # Setup mock arguments
        mock_parse_arguments.return_value = MagicMock(
            previous_release='1.1',
            new_release='1.2.0',
            dry_run=True,
            silent=True
        )

        # Setup other mocks
        mock_create_release_notes_md.return_value = "Release Notes"
        mock_get_comprehensive_release_notes.return_value = {}

        with patch('comprehensive_release_notes.os.getenv') as mock_getenv:
            mock_getenv.return_value = 'test_token'

            main()

            # Check if Github object is instantiated
            mock_github.assert_called_with('test_token')

            # Check if create_git_tag_and_release is not called due to dry_run flag
            meta_repo = mock_github.return_value.get_repo.return_value
            meta_repo.create_git_tag_and_release.assert_not_called()


if __name__ == '__main__':
    unittest.main()
