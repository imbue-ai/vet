import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Tuple

import requests

from vet.git_utils import SyncLocalGitRepo


def get_env(name: str, required: bool = True) -> str:
    value = os.environ.get(name)
    if required and not value:
        print(f"::error::{name} environment variable not set")
        sys.exit(1)
    return value or ""


def compute_merge_base(base_ref: str, head_sha: str) -> str:
    repo = SyncLocalGitRepo(Path("."))
    try:
        return repo.get_merge_base(f"origin/{base_ref}", head_sha)
    except Exception:
        print(f"::error::Failed to compute merge base between origin/{base_ref} and {head_sha}")
        sys.exit(1)


def build_vet_args(goal: str, merge_base: str) -> list[str]:
    args = [
        goal,
        "--quiet",
        "--output-format",
        "github",
        "--base-commit",
        merge_base,
    ]

    # Multi-value flags (must replicate bash word-splitting behavior)
    multi_value_envs = {
        "INPUT_ENABLED_ISSUE_CODES": "--enabled-issue-codes",
        "INPUT_DISABLED_ISSUE_CODES": "--disabled-issue-codes",
        "INPUT_EXTRA_CONTEXT": "--extra-context",
    }

    # Single-value flags
    single_value_envs = {
        "INPUT_MODEL": "--model",
        "INPUT_CONFIDENCE_THRESHOLD": "--confidence-threshold",
        "INPUT_MAX_WORKERS": "--max-workers",
        "INPUT_MAX_SPEND": "--max-spend",
        "INPUT_TEMPERATURE": "--temperature",
        "INPUT_CONFIG": "--config",
    }

    # Agentic flag
    if os.environ.get("INPUT_AGENTIC") == "true":
        args.append("--agentic")

    # Handle single-value flags
    for env_key, flag in single_value_envs.items():
        value = os.environ.get(env_key)
        if value:
            args.extend([flag, value])

    # Handle multi-value flags (space-splitting like bash)
    for env_key, flag in multi_value_envs.items():
        value = os.environ.get(env_key)
        if value:
            args.append(flag)
            args.extend(value.split())

    return args


def run_vet(args: list[str]) -> Tuple[dict, int]:
    result = subprocess.run(
        ["vet"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    status = result.returncode

    # Mirror run.sh behavior
    if status not in (0, 10):
        print(f"::error::Vet failed with exit code {status}")
        print(result.stderr)
        sys.exit(status)

    try:
        review_json = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("::error::Failed to parse vet JSON output")
        print(result.stdout)
        sys.exit(1)

    return review_json, status


def post_review(review_json: dict, repo: str, pr_number: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"

    try:
        response = requests.post(review_url, json=review_json, headers=headers)
        if response.status_code in (200, 201):
            return
    except Exception:
        # Fall through to comment fallback
        pass

    # Fallback: Post as PR comment (matches gh || fallback behavior)
    body_parts = [review_json.get("body", "")]

    for comment in review_json.get("comments", []):
        path = comment.get("path")
        line = comment.get("line")
        text = comment.get("body", "")
        body_parts.append(f"**{path}:{line}**\n\n{text}")

    comment_body = "\n\n---\n\n".join(body_parts)

    comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"

    try:
        requests.post(
            comment_url,
            json={"body": comment_body},
            headers=headers,
        )
    except Exception:
        # If this fails too, we allow workflow to continue
        pass


def main():
    goal = get_env("INPUT_GOAL")
    base_ref = get_env("INPUT_BASE_REF")
    head_sha = get_env("INPUT_HEAD_SHA")
    pr_number = get_env("INPUT_PR_NUMBER")
    repo = get_env("GITHUB_REPOSITORY")
    token = get_env("GH_TOKEN")

    fail_on_issues = os.environ.get("INPUT_FAIL_ON_ISSUES") == "true"

    merge_base = compute_merge_base(base_ref, head_sha)

    args = build_vet_args(goal, merge_base)

    review_json, status = run_vet(args)

    # Inject commit_id (replaces jq logic)
    review_json["commit_id"] = head_sha

    post_review(review_json, repo, pr_number, token)

    # Replicate fail-on-issues behavior
    if fail_on_issues and status == 10:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
