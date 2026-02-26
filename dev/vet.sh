#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

require_env_file

IMAGE_NAME="vet"
BUILD_ARG=""

for arg in "$@"; do
    if [ "$prev_arg" = "--agent-harness" ] && [ "$arg" = "claude" ]; then
        IMAGE_NAME="vet-claude"
        BUILD_ARG="claude"
    fi
    prev_arg="$arg"
done

ensure_image "$BUILD_ARG"

$RUNTIME run --rm \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file .env \
    "$IMAGE_NAME" /root/.local/bin/uv run vet "$@"
