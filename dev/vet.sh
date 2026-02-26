#!/bin/bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

echo "Ensuring $IMAGE_NAME image is up to date..."
if ! build_output=$("$SCRIPT_DIR/build.sh" 2>&1); then
    echo "Image build failed:"
    echo "$build_output"
    exit 1
fi

$RUNTIME run --rm \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file "$REPO_ROOT/.env" \
    "$IMAGE_NAME" /root/.local/bin/uv run vet "$@"
