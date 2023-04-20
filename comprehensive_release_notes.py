#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import re
import yaml
import argparse
from github import Github
from collections import defaultdict
from release_notes import (
    create_new_branch,
    get_sem_release,
    get_release_head,
    get_release_notes,
    create_release_notes_md,
    parse_arguments,
    verbose_print
)

META_REPOSITORY = "sequentech/meta"

REPOSITORIES = [
    "sequentech/common-ui",
    "sequentech/admin-console",
    "sequentech/election-portal",
    "sequentech/voting-booth",
    "sequentech/ballot-box",
    "sequentech/deployment-tool",
    "sequentech/tally-methods",
    "sequentech/tally-pipes",
    "sequentech/election-verifier",
    "sequentech/frestq",
    "sequentech/election-orchestra",
    "sequentech/iam",
    "sequentech/misc-tools",
    "sequentech/mixnet",
    "sequentech/documentation",
    "sequentech/ballot-verifier",
    "sequentech/release-tool",
]

def get_comprehensive_release_notes(args, token, repos, prev_release, new_release, config):
    """
    Generate comprehensive release notes for a list of repositories.

    Args:
        token (str): GitHub access token.
        repos (list): A list of repository paths, e.g., ["org/repo1", "org/repo2"].
        prev_release (str): The previous release version (e.g. "1.1.0").
        new_release (str): The new release version (e.g. "1.2.0").
        config (dict): the configuration for generating release notes.

    :return: dict, the release notes categorized by their labels.
    """
    gh = Github(token)
    release_notes = defaultdict(list)

    for repo_path in repos:
        verbose_print(args, f"Generating release notes for repo {repo_path}..")
        repo = gh.get_repo(repo_path)
        repo_notes = get_release_notes(gh, repo, prev_release, new_release, config)
        verbose_print(args, f"..generated")
        for category, notes in repo_notes.items():
            release_notes[category].extend(notes)

    # Deduplicate notes by removing duplicates based on links
    deduplicated_release_notes = {}
    links = set()
    for category, notes in release_notes.items():
        deduplicated_notes = []
        for note in notes:
            link = re.search(r'https://\S+', note)
            if link and link.group(0) not in links:
                deduplicated_notes.append(note)
                links.add(link.group(0))
        deduplicated_release_notes[category] = deduplicated_notes

    return deduplicated_release_notes

def parse_arguments():
    """
    Parse command-line arguments specific for the comprehensive release notes script.
    
    Returns:
        argparse.Namespace: An object containing parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description='Generate comprehensive release notes for multiple repositories.'
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


def main():
    args = parse_arguments()

    previous_release = args.previous_release
    new_release = args.new_release
    dry_run = args.dry_run
    github_token = os.getenv("GITHUB_TOKEN")

    g = Github(github_token)
    meta_repo = g.get_repo(META_REPOSITORY)

    with open(".github/release.yml") as f:
        config = yaml.safe_load(f)

    prev_major, prev_minor, prev_patch = get_sem_release(previous_release)
    new_major, new_minor, new_patch = get_sem_release(new_release)

    prev_release_head = get_release_head(prev_major, prev_minor, prev_patch)
    if new_patch or prev_major == new_major:
        new_release_head = get_release_head(new_major, new_minor, new_patch)
    else:
        new_release_head = meta_repo.default_branch

    verbose_print(args, f"Input Parameters: {args}")
    verbose_print(args, f"Previous Release Head: {prev_release_head}")
    verbose_print(args, f"New Release Head: {new_release_head}")

    release_notes = get_comprehensive_release_notes(
        args, github_token, REPOSITORIES, prev_release_head, new_release_head,
        config
    )

    if not new_patch:
        latest_release = meta_repo.get_releases()[0]
        latest_tag = latest_release.tag_name
        major, minor, new_patch = map(int, latest_tag.split("."))
        if new_major == major and new_minor == minor:
            new_patch += 1
        else:
            new_patch = 0

    new_tag = f"{new_major}.{new_minor}.{new_patch}"
    new_title = f"{new_tag} release"
    verbose_print(args, f"New Release Tag: {new_tag}")

    release_notes_md = create_release_notes_md(release_notes, new_tag)

    verbose_print(args, f"Generated Release Notes: {release_notes_md}")

    if not dry_run:
        if prev_major < new_major:
            verbose_print(args, "Creating new branch")
            create_new_branch(meta_repo, new_release_head)
        else:
            branch = None
            try:
                branch = meta_repo.get_branch(new_release_head)
            except:
                verbose_print(args, "Creating new branch")
                create_new_branch(meta_repo, new_release_head)
                branch = meta_repo.get_branch(new_release_head)

        verbose_print(args, "Creating new release")
        meta_repo.create_git_tag_and_release(
            tag=new_tag,
            tag_message=new_title,
            type='commit',
            object=branch.commit.sha,
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
