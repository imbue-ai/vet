from __future__ import annotations

import json
import os
from unittest.mock import patch

import httpx
import pytest

from vet.cli.post_review import _build_fallback_comment_body, main


def test_fallback_body_with_multiple_comments():
    review = {
        "body": "**Vet found 2 issues.**",
        "comments": [
            {"path": "src/app.py", "line": 10, "body": "Bug here"},
            {"path": "src/utils.py", "line": 42, "body": "Another bug"},
        ],
    }
    result = _build_fallback_comment_body(review)
    sections = result.split("\n\n---\n\n")
    assert len(sections) == 3
    assert sections[0] == "**Vet found 2 issues.**"
    assert sections[1] == "**src/app.py:10**\n\nBug here"
    assert sections[2] == "**src/utils.py:42**\n\nAnother bug"


SAMPLE_REVIEW = {
    "body": "**Vet found 1 issue.**",
    "event": "COMMENT",
    "comments": [
        {"path": "src/app.py", "line": 10, "side": "RIGHT", "body": "Bug here"},
    ],
}

REQUIRED_ENV = {
    "VET_REVIEW_JSON": "/tmp/review.json",
    "VET_COMMIT_SHA": "abc123def456",
    "VET_REPO": "owner/repo",
    "VET_PR_NUMBER": "42",
    "GH_TOKEN": "ghp_fake_token",
}


def _run_main_with_mock_transport(tmp_path, handle_request):
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(SAMPLE_REVIEW))
    env = {**REQUIRED_ENV, "VET_REVIEW_JSON": str(review_path)}
    transport = httpx.MockTransport(handle_request)

    with patch.dict(os.environ, env, clear=True):
        with patch(
            "vet.cli.post_review.httpx.Client",
            return_value=httpx.Client(transport=transport),
        ):
            return main()


def test_main_review_succeeds_and_adds_commit_id(tmp_path):
    posted_payload = {}

    def handle_request(request: httpx.Request) -> httpx.Response:
        if "/reviews" in str(request.url):
            posted_payload.update(json.loads(request.content))
            return httpx.Response(200)
        return httpx.Response(404)

    assert _run_main_with_mock_transport(tmp_path, handle_request) == 0
    assert posted_payload["commit_id"] == "abc123def456"
    assert posted_payload["body"] == SAMPLE_REVIEW["body"]


def test_main_review_fails_falls_back_to_comment_and_returns_zero(tmp_path):
    requests_made = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests_made.append(str(request.url))
        if "/reviews" in str(request.url):
            return httpx.Response(422)
        if "/comments" in str(request.url):
            return httpx.Response(201)
        return httpx.Response(404)

    assert _run_main_with_mock_transport(tmp_path, handle_request) == 0
    assert any("/reviews" in url for url in requests_made)
    assert any("/comments" in url for url in requests_made)
