#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

require_env_file

IMAGE_NAME="vet"
BUILD_ARG=""

if [ "$1" = "claude" ]; then
    IMAGE_NAME="vet-claude"
    BUILD_ARG="claude"
fi

ensure_image "$BUILD_ARG"

$RUNTIME run --rm -it \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file .env \
    "$IMAGE_NAME" bash
