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

# Read .env and derive image settings from I_CHOOSE_CONVENIENCE_OVER_FREEDOM.
require_env_file
set -a
source .env
set +a

IMAGE_NAME="vet"
INSTALL_CLAUDE="false"
if [ "${I_CHOOSE_CONVENIENCE_OVER_FREEDOM:-}" = "true" ]; then
    IMAGE_NAME="vet-claude"
    INSTALL_CLAUDE="true"
fi

ensure_image() {
    echo "Ensuring $IMAGE_NAME image is up to date..."
    local build_output
    if ! build_output=$("$SCRIPT_DIR/build.sh" 2>&1); then
        echo "Image build failed:"
        echo "$build_output"
        exit 1
    fi
}

run_vet() {
    ensure_image

    $RUNTIME run --rm \
        --mount type=bind,source="$(pwd)",target=/app \
        --env-file .env \
        "$IMAGE_NAME" /root/.local/bin/uv run vet "$@"
}
