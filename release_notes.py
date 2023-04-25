#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import re
import yaml
import argparse
from datetime import datetime
from github import Github

def get_label_category(labels, categories):
    """
    Get the category that matches the given labels.

    Args:
        labels (list): A list of labels from a pull request.
        categories (list): A list of categories from the configuration.

    Returns:
        dict: The matching category, or None if no category matches.
    """
    for category in categories:
        for label in labels:
            if label.name in category["labels"] or '*' in category["labels"]:
                return category
    return None

def get_commit_pull(commit):
    """
    Get the pull request (PR) object associated with a commit.

    This function uses the PyGithub library to find the PR associated with a given commit.
    It first checks if the commit message's first line contains one or more PR numbers (e.g. "#33").
    If so, it chooses the largest PR number and returns the corresponding PR object.
    Otherwise, it returns the PR object with the lowest PR number from commit.get_pulls().

    :param commit: A PyGithub Commit object representing a commit.
    :return: A PyGithub PullRequest object corresponding to the associated PR, or None if no PR is found.
    """
    # Extract PR numbers from the commit message's first line
    first_line = commit.commit.message.split("\n")[0]
    pr_numbers = [int(x[1:]) for x in re.findall(r"#\d+", first_line)]

    if pr_numbers:
        # Find the PR with the largest number mentioned in the commit message
        max_pr_number = max(pr_numbers)
        associated_pr = None

        # Iterate over the available pull requests and find the one with the max_pr_number
        for pr in commit.get_pulls():
            if pr.number == max_pr_number:
                associated_pr = pr
                break

        return associated_pr
    else:
        # If no PR numbers are mentioned in the commit message, find the PR with the lowest number
        min_pr = None

        for pr in commit.get_pulls():
            if min_pr is None or pr.number < min_pr.number:
                min_pr = pr

        return min_pr

def get_github_issue_from_link(link_text, github):
    """
    Retrieve the Github issue object from the provided link.

    Args:
        link_text (str): The link to the Github issue, in the format 'https://github.com/owner/repo/issues/123'.
        github (Github): A PyGithub object that represents a connection to a Github account.

    Returns:
        object: A PyGithub object that represents the retrieved Github issue.
    """
    # Extracting the owner, repository name, and issue number from the link
    owner, repo, _, issue_number = link_text.split("/")[-4:]

    # Getting the repository object
    repo = github.get_repo(f"{owner}/{repo}")

    # Getting the issue object
    issue = repo.get_issue(int(issue_number))

    return issue

def get_release_notes(github, repo, previous_release_head, new_release_head, config, args=type('', (), {'silent': False})()):
    """
    Retrieve release notes from a GitHub repository based on the given configuration.

    :param github: A PyGithub object that represents a connection to a Github account.
    :param repo: A Repository object representing the GitHub repository.
    :param previous_release_head: str, the previous release's head commit.
    :param new_release_head: str, the new release's head commit.
    :param config: dict, the configuration for generating release notes.
    :return: dict, the release notes categorized by their labels.
    """
    compare_branches = repo.compare(previous_release_head, new_release_head)

    release_notes = {}
    parent_issues = []
    links = []

    for commit in compare_branches.commits:
        pr = get_commit_pull(commit)
        if pr == None:
            continue

        if any(label.name in config["changelog"]["exclude"]["labels"] for label in pr.labels):
            continue

        category = get_label_category(pr.labels, config["changelog"]["categories"])
        if category is None:
            continue

        title = pr.title.strip()
        parent_issue_text = "Parent issue: "
        parent_issue = None
        if isinstance(pr.body, str):
            for line in pr.body.split("\n"):
                if line.startswith(parent_issue_text):
                    parent_issue = line[len(parent_issue_text):]
                    break

        if parent_issue:
            if parent_issue in parent_issues:
                continue
            else:
                parent_issues.append(parent_issue)
            link = parent_issue
            issue = get_github_issue_from_link(link, github)
            title = issue.title.strip()
        else:
            link = pr.html_url
        
        if link in links:
            continue
        else:
            links.append(link)

        if category['title'] not in release_notes:
            release_notes[category['title']] = []

        development = f"* {title} by @{pr.user.login} in {link}"
        release_notes[category['title']].append(development)

    release_notes_yaml = yaml.dump(release_notes, default_flow_style=False)
    verbose_print(args, f"release notes:\n{release_notes_yaml}")
    return release_notes

def create_release_notes_md(release_notes, new_release):
    """
    Convert the generated release notes into Markdown format.

    Args:
        release_notes (dict): The release notes, organized by category.
        new_release (str): The new release version (e.g. "1.1.0").

    Returns:
        str: The release notes in Markdown format.
    """
    md = f"<!-- Release notes generated using configuration in .github/release.yml at {new_release} -->\n\n"
    md += "## What's Changed\n"
    for category, notes in release_notes.items():
        if notes:
            md += f"### {category}\n"
            md += "\n".join(notes) + "\n"
    return md

def parse_arguments():
    """
    Parse command-line arguments.
    
    Returns:
        argparse.Namespace: An object containing parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description='Generate release notes and create a new release.'
    )
    parser.add_argument(
        'repo_path',
        help='Github Repository path, i.e. `sequentech/ballot-box`'
    )
    parser.add_argument(
        'previous_release',
        help='Previous release version in format `<major>.<minor>`, i.e. `7.2`'
    )
    parser.add_argument(
        'new_release',
        help=(
            'New release version in format `<major>.<minor>`, i.e. `7.2` '
            'or full semver release if it already exists i.e. `7.3.0`'
        )
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help=(
            'Output the release notes but do not create any tag, release or '
            'new branch.'
        )
    )
    parser.add_argument(
        '--silent',
        action='store_true',
        help='Disables verbose output'
    )
    parser.add_argument(
        '--draft',
        action='store_true',
        help='Mark the new release be as draft'
    )
    parser.add_argument(
        '--prerelease',
        action='store_true',
        help='Mark the new release be as a prerelease'
    )
    return parser.parse_args()

def create_new_branch(repo, new_branch):
    """
    Create a new branch for the release.

    Args:
        repo (github.Repository.Repository): The repository object.
        prev_major (int): The previous major version.
        new_major (int): The new major version.
        new_minor (int): The new minor version.
    """
    default_branch = repo.default_branch
    repo.create_git_ref(f"refs/heads/{new_branch}", repo.get_branch(default_branch).commit.sha)

def get_sem_release(release_string):
    """
    Returns the major, minor, and patch numbers of a software release in
    Semantic Versioning format given as a string.

    Args:
        release_string (str): A string representing the software release in
            Semantic Versioning format. Example: "2.4.1".

    Returns:
    A tuple of three integers representing the major, minor, and patch
    numbers of the release respectively. If the release_string does not
    contain a patch number, the third element of the tuple will be None.

    Example:
    >>> get_sem_release_numbers("2.4.1")
    (2, 4, 1)

    >>> get_sem_release_numbers("1.10")
    (1, 10, None)
    """
    release_string_list = release_string.split(".")
    major = int(release_string_list[0])
    minor = int(release_string_list[1])
    patch = release_string_list[2] if len(release_string_list) >= 3 else None
    return (major, minor, patch)

def get_release_head(major, minor, patch):
    """
    Returns a formatted version string based on the given major, minor, and patch version numbers.
    
    Args:
        major (int): The major version number.
        minor (int): The minor version number.
        patch (int or None): The patch version number, or None if there is no patch.

    Returns:
        str: A formatted version string with the structure "major.minor.patch" or "major.minor.x" if patch is None.
    """
    if not patch:
        return f"{major}.{minor}.x"
    else:
        return f"{major}.{minor}.{patch}"

def verbose_print(args, message):
    if not args.silent:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

def main():
    args = parse_arguments()

    repo_path = args.repo_path
    previous_release = args.previous_release
    new_release = args.new_release
    dry_run = args.dry_run
    github_token = os.getenv("GITHUB_TOKEN")

    gh = Github(github_token)
    repo = gh.get_repo(repo_path)

    with open(".github/release.yml") as f:
        config = yaml.safe_load(f)

    prev_major, prev_minor, prev_patch = get_sem_release(previous_release)
    new_major, new_minor, new_patch = get_sem_release(new_release)

    prev_release_head = get_release_head(prev_major, prev_minor, prev_patch)
    if new_patch or prev_major == new_major:
        new_release_head = get_release_head(new_major, new_minor, new_patch)
    else:
        new_release_head = repo.default_branch

    verbose_print(args, f"Input Parameters: {args}")
    verbose_print(args, f"Previous Release Head: {prev_release_head}")
    verbose_print(args, f"New Release Head: {new_release_head}")

    release_notes = get_release_notes(gh, repo, prev_release_head, new_release_head, config, args)

    if not new_patch:
        latest_release = repo.get_releases()[0]
        latest_tag = latest_release.tag_name
        major, minor, new_patch = map(int, latest_tag.split("."))
        if new_major == major and new_minor == minor:
            new_patch += 1
        else:
            new_patch = 0

    new_tag = f"{new_major}.{new_minor}.{new_patch}"
    new_title = f"{new_tag} release"
    verbose_print(args, f"New Release Tag: {new_tag}")
    verbose_print(args, f"New Release Title: {new_title}")

    release_notes_md = create_release_notes_md(release_notes, new_tag)

    verbose_print(args, f"Generated Release Notes: {release_notes_md}")

    if not dry_run:
        if prev_major < new_major:
            verbose_print(args, "Creating new branch")
            create_new_branch(repo, new_release_head)
        verbose_print(args, "Creating new release")
        repo.create_git_tag_and_release(
            tag=new_tag,
            tag_message=new_title,
            type='commit',
            object=repo.get_branch(new_release_head).commit.sha,
            release_name=new_title,
            release_message=release_notes_md,
            prerelease=args.prerelease,
            draft=args.draft
        )
        verbose_print(args, f"Executed Actions: Branch created and new release created")
    else:
        verbose_print(args, "Dry Run: No actions executed")

if __name__ == "__main__":
    main()
