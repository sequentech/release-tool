#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023 Sequent Tech Inc <legal@sequentech.io>
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import re
import requests
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


def send_graphql_query(query, access_token, silent):
    """
    Send a GraphQL query to the GitHub API.

    :param query: str, the GraphQL query
    :param access_token: str, the access token for GitHub API
    :param silent: bool, flag for silent mode
    :return: dict, the JSON response from the API
    """
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    request_data = {"query": query}
    response = requests.post(
        "https://api.github.com/graphql",
        json=request_data,
        headers=headers
    )

    if response.status_code != 200:
        verbose_print(f"ERROR GraphQL request failed with status {response.status_code}: {response.text}", silent)
        return None

    return response.json()

def get_project_id(access_token, project_board_url, silent):
    """
    Find and return a Github project given its URL.
    
    :param access_token: str, the access token for GitHub API
    :param project_board_url: str, URL of the project board
    :param silent: bool, flag for silent mode
    :return: github.Project.Project instance or None
    """

    # Extract project number and organization name from the URL
    org_name = re.search(r"https://github.com/orgs/([\w-]+)/", project_board_url).group(1)
    project_num = int(re.search(r"/projects/(\d+)", project_board_url).group(1))

    verbose_print(f"- Github org_name = `{org_name}`", silent)
    verbose_print(f"- Github project_num = int({project_num})`", silent)
    verbose_print(f"Obtaining project_id ...", silent)

    query = f"""
    query {{
        organization(login: "{org_name}") {{
            projectV2(number: {project_num}) {{
                id
            }}
        }}
    }}
    """
    response = send_graphql_query(query, access_token, silent)
    if response is None or "errors" in response:
        return None

    project_id = response["data"]["organization"]["projectV2"]["id"]
    verbose_print(f"... Done! Github project_id = `{project_id}`", silent)
    return project_id

def get_closed_issues_in_last_n_days(project_id, days, access_token, silent):
    """
    Get all closed issues in the last N days for a given project.
    
    :param project_id: str, the ID of the project
    :param days: int, number of days to look back for closed issues
    :param access_token: str, the access token for GitHub API
    :param silent: bool, flag for silent mode
    :return: list of github.Issue.Issue instances
    """
    now = datetime.now()
    n_days_ago = now - timedelta(days=days)
    closed_issues = []

    has_next_page = True
    end_cursor = None
    total_count = 0

    verbose_print(f"Obtaining project_id=`{project_id}` issues ..", silent)
    while has_next_page:
        verbose_print("...", silent)
        query = f"""
        query {{
            node(id: "{project_id}") {{
                ... on ProjectV2 {{
                    items(first: 100{f', after: "{end_cursor}"' if end_cursor else ''}) {{
                        nodes {{
                            id
                            updatedAt
                            content {{
                                __typename
                                ... on Issue {{
                                    title
                                    closedAt
                                    state
                                    body
                                    url
                                    repository {{ name }}
                                    assignees(first: 1) {{
                                        nodes {{
                                        login
                                        }}
                                    }}
                                }}
                            }}
                        }}
                        totalCount
                        pageInfo {{
                            hasNextPage
                            endCursor
                        }}
                    }}
                }}
            }}
        }}
        """

        response = send_graphql_query(query, access_token, silent)
        if response is None or "errors" in response:
            break

        nodes = response["data"]["node"]["items"]["nodes"]
        page_info = response["data"]["node"]["items"]["pageInfo"]
        total_count = response["data"]["node"]["items"]['totalCount']
        has_next_page = page_info["hasNextPage"]
        end_cursor = page_info["endCursor"]

        for node in nodes:
            if (
                node["content"]["__typename"] == "Issue"
                and node["content"]["state"] == "CLOSED"
            ):
                issue_closed_at = datetime.strptime(
                    node["content"]["closedAt"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if issue_closed_at > n_days_ago:
                    closed_issues.append(node)

    verbose_print(f"...done! read {total_count} issues, filtered to {len(closed_issues)} issues", silent)

    return closed_issues


def update_pull_request_body(pr_url, access_token, start_text, silent, dry_run):
    verbose_print(f"\t- PR {pr_url}:", silent)
    # Extract the repository name, owner and pull request number from the URL
    split_url = pr_url.split("/")
    owner, repo, pr_number = split_url[3], split_url[4], split_url[-1]

    # Prepare the GraphQL query to get the pull request's ID and body
    query = f"""
    query {{
        repository(owner: "{owner}", name: "{repo}") {{
            pullRequest(number: {pr_number}) {{
                id
                body
            }}
        }}
    }}
    """

    # Execute the query
    response_data = send_graphql_query(query, access_token, silent)

    # Parse the response
    pr_data = response_data["data"]["repository"]["pullRequest"]
    pr_id, current_body = pr_data["id"], pr_data["body"]

    # Check if the desired text is at the start of the body
    verbose_print(f"\t\t - Body starts with ```{current_body[:200]}```", silent)
    if current_body.startswith(start_text):
        verbose_print(f"\t\t - Not updating, it's ok", silent)
        return

    # If not, update the body to include the desired text at the beginning
    new_body = start_text + "\n" + current_body

    # Prepare the GraphQL mutation to update the pull request body
    mutation_query = f"""
    mutation {{
        updatePullRequest(input: {{
            pullRequestId: "{pr_id}",
            body: "{new_body}"
        }}) {{
            pullRequest {{
                number
                body
            }}
        }}
    }}
    """

    if dry_run:
        verbose_print(f"\t\t - [dry-run] Would be updating PR to be ```{new_body[:300]}```", silent)
        return
    else:
        verbose_print(f"\t\t - Updating PR..", silent)
    
    # Execute the mutation
    response_data = send_graphql_query(mutation_query, access_token, silent)
    verbose_print(f"\t\t   ... done!", silent)

def update_prs_with_parent_issue(issue, access_token, dry_run, silent):
    """
    Update PRs associated with a closed issue by adding a "Parent issue" link to their body.
    
    :param issue: github.Issue.Issue instance
    :param dry_run: bool, indicating whether the code should perform changes or not
    :param silent: bool, flag for silent mode
    """
    issue_title = issue["content"]["title"]
    issue_url = issue["content"]["url"]
    issue_body = issue["content"]["body"]
    pr_links = re.findall(r"https://github.com/\S+/pull/\d+", issue_body)
    verbose_print(f"- Issue: {issue_url} ({issue_title})", silent)

    for pr_link in pr_links:
        start_text = f"Parent issue: {issue_url}\n"
        update_pull_request_body(
            pr_link, access_token, start_text, silent, dry_run
        )

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

    project = get_project_id(access_token, args.project_board_url, args.silent)

    if project is None:
        verbose_print("ERROR Project not found", args.silent)
        exit(1)


    closed_issues = get_closed_issues_in_last_n_days(
        project, args.days, access_token, args.silent
    )

    for issue in closed_issues:
        update_prs_with_parent_issue(
            issue, access_token, args.dry_run, args.silent
        )

if __name__ == "__main__":
    main()
