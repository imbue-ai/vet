#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v podman &> /dev/null; then
    RUNTIME="podman"
elif command -v docker &> /dev/null; then
    RUNTIME="docker"
else
    echo "No containerization program detected. Please install podman (preferred) or docker."
    exit 1
fi

require_env_file() {
    [ -f .env ] || { echo '.env file not found, please create one before proceeding'; exit 1; }
}

ensure_image() {
    local build_arg="${1:-}"
    local image_name="vet"
    if [ "$build_arg" = "claude" ]; then
        image_name="vet-claude"
    fi

    echo "Ensuring $image_name image is up to date..."
    local build_output
    if ! build_output=$("$SCRIPT_DIR/build.sh" "$build_arg" 2>&1); then
        echo "Image build failed:"
        echo "$build_output"
        exit 1
    fi
}

run_vet() {
    local image_name="$1"
    local build_arg="$2"
    shift 2

    require_env_file
    ensure_image "$build_arg"

    $RUNTIME run --rm \
        --mount type=bind,source="$(pwd)",target=/app \
        --env-file .env \
        "$image_name" /root/.local/bin/uv run vet "$@"
}
