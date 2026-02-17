#!/usr/bin/env bash
set +e

# Compute merge base
MERGE_BASE=$(git merge-base "origin/${INPUT_BASE_REF}" "${INPUT_HEAD_SHA}")
if [ $? -ne 0 ]; then
  echo "::error::Failed to compute merge base between origin/${INPUT_BASE_REF} and ${INPUT_HEAD_SHA}"
  exit 1
fi

# Build vet command arguments
ARGS=("${INPUT_GOAL}" --quiet --output-format github --base-commit "${MERGE_BASE}")

[[ "${INPUT_AGENTIC}" == "true" ]] && ARGS+=(--agentic)
[[ -n "${INPUT_MODEL}" ]] && ARGS+=(--model "${INPUT_MODEL}")
[[ -n "${INPUT_CONFIDENCE_THRESHOLD}" ]] && ARGS+=(--confidence-threshold "${INPUT_CONFIDENCE_THRESHOLD}")
[[ -n "${INPUT_MAX_WORKERS}" ]] && ARGS+=(--max-workers "${INPUT_MAX_WORKERS}")
[[ -n "${INPUT_MAX_SPEND}" ]] && ARGS+=(--max-spend "${INPUT_MAX_SPEND}")
[[ -n "${INPUT_TEMPERATURE}" ]] && ARGS+=(--temperature "${INPUT_TEMPERATURE}")
[[ -n "${INPUT_CONFIG}" ]] && ARGS+=(--config "${INPUT_CONFIG}")

if [[ -n "${INPUT_ENABLED_ISSUE_CODES}" ]]; then
  # shellcheck disable=SC2086
  ARGS+=(--enabled-issue-codes ${INPUT_ENABLED_ISSUE_CODES})
fi

if [[ -n "${INPUT_DISABLED_ISSUE_CODES}" ]]; then
  # shellcheck disable=SC2086
  ARGS+=(--disabled-issue-codes ${INPUT_DISABLED_ISSUE_CODES})
fi

if [[ -n "${INPUT_EXTRA_CONTEXT}" ]]; then
  # shellcheck disable=SC2086
  ARGS+=(--extra-context ${INPUT_EXTRA_CONTEXT})
fi

# Run vet
vet "${ARGS[@]}" > "${RUNNER_TEMP}/review.json"
status=$?

# Exit codes: 0 = no issues, 10 = issues found, anything else = error
if [ "$status" -ne 0 ] && [ "$status" -ne 10 ]; then
  echo "::error::Vet failed with exit code ${status}"
  exit "$status"
fi

# Inject commit SHA into review JSON for GitHub API
jq --arg sha "${INPUT_HEAD_SHA}" \
  '. + {commit_id: $sha}' "${RUNNER_TEMP}/review.json" > "${RUNNER_TEMP}/review-final.json"

# Post review via GitHub API, falling back to PR comment
gh api "repos/${GITHUB_REPOSITORY}/pulls/${INPUT_PR_NUMBER}/reviews" \
  --method POST --input "${RUNNER_TEMP}/review-final.json" > /dev/null || \
  gh pr comment "${INPUT_PR_NUMBER}" \
    --body "$(jq -r '[.body] + [.comments[] | "**\(.path):\(.line)**\n\n\(.body)"] | join("\n\n---\n\n")' "${RUNNER_TEMP}/review-final.json")"

# Optionally fail CI when issues are found
if [[ "${INPUT_FAIL_ON_ISSUES}" == "true" ]] && [ "$status" -eq 10 ]; then
  exit 1
fi

exit 0
