#!/usr/bin/env bash
set +e

MERGE_BASE=$(git merge-base "origin/${INPUT_BASE_REF}" "${INPUT_HEAD_SHA}")
if [ $? -ne 0 ]; then
  echo "::error::Failed to compute merge base between origin/${INPUT_BASE_REF} and ${INPUT_HEAD_SHA}"
  exit 1
fi

ARGS=("${INPUT_GOAL}" --quiet --output-format github --base-commit "${MERGE_BASE}")

[[ "${INPUT_AGENTIC}" == "true" ]] && ARGS+=(--agentic)
[[ -n "${INPUT_MODEL}" ]] && ARGS+=(--model "${INPUT_MODEL}")
[[ -n "${INPUT_CONFIDENCE_THRESHOLD}" ]] && ARGS+=(--confidence-threshold "${INPUT_CONFIDENCE_THRESHOLD}")
[[ -n "${INPUT_MAX_WORKERS}" ]] && ARGS+=(--max-workers "${INPUT_MAX_WORKERS}")
[[ -n "${INPUT_MAX_SPEND}" ]] && ARGS+=(--max-spend "${INPUT_MAX_SPEND}")
[[ -n "${INPUT_TEMPERATURE}" ]] && ARGS+=(--temperature "${INPUT_TEMPERATURE}")
[[ -n "${INPUT_CONFIG}" ]] && ARGS+=(--config "${INPUT_CONFIG}")

[[ -n "${INPUT_ENABLED_ISSUE_CODES}" ]] && ARGS+=(--enabled-issue-codes ${INPUT_ENABLED_ISSUE_CODES})
[[ -n "${INPUT_DISABLED_ISSUE_CODES}" ]] && ARGS+=(--disabled-issue-codes ${INPUT_DISABLED_ISSUE_CODES})
[[ -n "${INPUT_EXTRA_CONTEXT}" ]] && ARGS+=(--extra-context ${INPUT_EXTRA_CONTEXT})

vet "${ARGS[@]}" > "${RUNNER_TEMP}/review.json"
status=$?

if [ "$status" -ne 0 ] && [ "$status" -ne 10 ]; then
  echo "::error::Vet failed with exit code ${status}"
  exit "$status"
fi

jq --arg sha "${INPUT_HEAD_SHA}" \
  '. + {commit_id: $sha}' "${RUNNER_TEMP}/review.json" > "${RUNNER_TEMP}/review-final.json"

gh api "repos/${GITHUB_REPOSITORY}/pulls/${INPUT_PR_NUMBER}/reviews" \
  --method POST --input "${RUNNER_TEMP}/review-final.json" > /dev/null || \
  gh pr comment "${INPUT_PR_NUMBER}" \
    --body "$(jq -r '[.body] + [.comments[] | "**\(.path):\(.line)**\n\n\(.body)"] | join("\n\n---\n\n")' "${RUNNER_TEMP}/review-final.json")"

if [[ "${INPUT_FAIL_ON_ISSUES}" == "true" ]] && [ "$status" -eq 10 ]; then
  exit 1
fi

exit 0
