from __future__ import annotations

import json
import os
import sys

import httpx
from loguru import logger

GITHUB_API_BASE = "https://api.github.com"

REQUIRED_ENV_VARS = {
    "VET_REVIEW_JSON": "Path to the review JSON file produced by vet --output-format github",
    "VET_COMMIT_SHA": "The PR head commit SHA",
    "VET_REPO": "The GitHub repository in owner/repo format",
    "VET_PR_NUMBER": "The PR number",
    "GH_TOKEN": "GitHub token for API authentication",
}


def _get_env_vars() -> dict[str, str]:
    """Read and validate all required environment variables."""
    values = {}
    missing = []
    for var, description in REQUIRED_ENV_VARS.items():
        value = os.environ.get(var)
        if not value:
            missing.append(f"  {var}: {description}")
        else:
            values[var] = value

    if missing:
        logger.error("Missing required environment variables:\n" + "\n".join(missing))
        sys.exit(2)

    return values


def _build_fallback_comment_body(review: dict) -> str:
    """Build a markdown comment body from the review JSON."""
    sections = [review["body"]]
    for comment in review.get("comments", []):
        sections.append(f"**{comment['path']}:{comment['line']}**\n\n{comment['body']}")
    return "\n\n---\n\n".join(sections)


def _post_review(
    client: httpx.Client,
    repo: str,
    pr_number: str,
    payload: dict,
) -> bool:
    """POST the review to GitHub's PR reviews API. Returns True on success."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/reviews"
    try:
        response = client.post(url, json=payload)
    except httpx.HTTPError:
        logger.warning("Review API call failed (network error), falling back to PR comment")
        return False
    if response.is_success:
        return True
    logger.warning(
        "Review API call failed (status {}), falling back to PR comment",
        response.status_code,
    )
    return False


def _post_comment(
    client: httpx.Client,
    repo: str,
    pr_number: str,
    body: str,
) -> None:
    """POST a fallback comment to the PR."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/comments"
    response = client.post(url, json={"body": body})
    response.raise_for_status()


def main() -> int:
    env = _get_env_vars()

    review_path = env["VET_REVIEW_JSON"]
    commit_sha = env["VET_COMMIT_SHA"]
    repo = env["VET_REPO"]
    pr_number = env["VET_PR_NUMBER"]
    gh_token = env["GH_TOKEN"]

    with open(review_path) as f:
        review = json.load(f)

    review["commit_id"] = commit_sha

    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github+json",
    }

    with httpx.Client(headers=headers) as client:
        if not _post_review(client, repo, pr_number, review):
            fallback_body = _build_fallback_comment_body(review)
            try:
                _post_comment(client, repo, pr_number, fallback_body)
            except httpx.HTTPError:
                logger.warning("Fallback comment also failed")

    return 0


# THIS IS A BAD COMMENT CATCH ME IN REVIEW
if __name__ == "__main__":
    sys.exit(main())
