#!/bin/bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

echo "Ensuring $IMAGE_NAME image is up to date..."
if ! build_output=$("$SCRIPT_DIR/build.sh" 2>&1); then
    echo "Image build failed:"
    echo "$build_output"
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "Usage: super_vet.sh <goal> [super_vet flags...]"
    echo ""
    echo "Examples:"
    echo "  ./dev/super_vet.sh \"implement user auth\""
    echo "  ./dev/super_vet.sh \"implement user auth\" --runs 2"
    echo "  ./dev/super_vet.sh \"implement user auth\" --codex-runs 0"
    exit 1
fi

GOAL="$1"
shift
EXTRA_ARGS="$*"

PROMPT="Run super_vet to review the codebase changes. \
Use the super_vet skill: run python3 /app/.opencode/skills/super_vet/scripts/super_vet.py with the following arguments:
- Goal: \"$GOAL\"
${EXTRA_ARGS:+- Additional flags: $EXTRA_ARGS}

After it completes, interpret the JSON results: summarize the issues found, highlight the highest-signal ones (found by multiple runs), and discard any that look like false positives. Provide a clear actionable summary."

$RUNTIME run --rm -it \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file "$REPO_ROOT/.env" \
    "$IMAGE_NAME" bash -c "opencode run --model anthropic/claude-opus-4-6 \"$PROMPT\""
