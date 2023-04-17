#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import re
import argparse
from github import Github
from datetime import datetime, timedelta

def verbose_print(message, silent):
    """
    Print a timestamped message if silent mode is not enabled.

    :param message: str, message to be printed
    :param silent: bool, flag for silent mode
    """
    if not silent:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

def get_project_by_url(github_instance, project_board_url, silent):
    """
    Find and return a Github project given its URL.
    
    :param github_instance: github.Github instance
    :param project_board_url: str, URL of the project board
    :param silent: bool, flag for silent mode
    :return: github.Project.Project instance or None
    """
    org_name = re.search(r"https://github.com/orgs/([\w-]+)/", project_board_url).group(1)
    org = github_instance.get_organization(org_name)
    
    # Extract project ID from the URL
    project_id = int(re.search(r"/projects/(\d+)", project_board_url).group(1))
    verbose_print(f"- Github org_name = `{org_name}`", silent)
    verbose_print(f"- Github project_id = int({project_id})`", silent)
    
    for project in org.get_projects():
        verbose_print(f"... Github project_id = int({id})`", silent)
        if project.id == project_id:
            return project
    return None

def get_closed_issues_in_last_n_days(project, days):
    """
    Get all closed issues in the last N days for a given project.
    
    :param project: github.Project.Project instance
    :param days: int, number of days to look back for closed issues
    :return: list of github.Issue.Issue instances
    """
    now = datetime.now()
    n_days_ago = now - timedelta(days=days)
    closed_issues = []

    for column in project.get_columns():
        for card in column.get_cards():
            if card.get_content() is not None and "/issues/" in card.content_url:
                issue = card.get_content()
                if issue.state == "closed" and issue.closed_at > n_days_ago:
                    closed_issues.append(issue)

    return closed_issues

def update_prs_with_parent_issue(issue, dry_run, silent):
    """
    Update PRs associated with a closed issue by adding a "Parent issue" link to their body.
    
    :param issue: github.Issue.Issue instance
    :param dry_run: bool, indicating whether the code should perform changes or not
    :param silent: bool, flag for silent mode
    """
    pr_links = re.findall(r"https://github.com/\S+/pull/\d+", issue.body)
    verbose_print(f"- Issue: {issue.html_url} ({issue.title})", silent)

    for pr_link in pr_links:
        pr = issue.repository.get_pull(int(pr_link.split("/")[-1]))

        if not pr.body.startswith(issue.html_url):
            pr_body = f"Parent issue: {issue.html_url}\n\n{pr.body}"
            if not dry_run:
                verbose_print(f"\t- FIXING Linked PR: {pr.html_url} ({pr.title})", silent)
                pr.edit(body=pr_body)
            else:
                verbose_print(f"\t- (dry-run) FIXING Linked PR: {pr.html_url} ({pr.title}). Current body starts with:\n{pr.body[300:]}\n[...]", silent)
        else:
            verbose_print(f"\t- PASS Linked PR: {pr.html_url} ({pr.title})", silent)

def main():
    """
    Main function to update PRs with a "Parent issue" link for closed issues in the last N days.
    """
    parser = argparse.ArgumentParser(description="Add Parent Issue links to related PRs for closed issues in the last N days.")
    parser.add_argument("project_board_url", help="The URL of the project board.")
    parser.add_argument("--dry-run", action="store_true", help="Don't modify PRs, just simulate changes.")
    parser.add_argument("--days", type=int, default=180, help="The number of days to look back for closed issues. Default is 180.")
    parser.add_argument("--silent", action="store_true", help="Don't print verbose messages.")
    args = parser.parse_args()

    access_token = os.environ.get("GITHUB_TOKEN")

    verbose_print(f"Input Parameters: {args}", args.silent)

    if access_token is None:
        verbose_print("ERROR Environment variable 'GITHUB_TOKEN' not set.", args.silent)
        exit(1)

    github_instance = Github(access_token)
    project = get_project_by_url(github_instance, args.project_board_url, args.silent)

    if project is None:
        verbose_print("ERROR Project not found", args.silent)
        exit(1)


    closed_issues = get_closed_issues_in_last_n_days(project, args.days)

    for issue in closed_issues:
        update_prs_with_parent_issue(issue, args.dry_run, args.silent)

if __name__ == "__main__":
    main()
