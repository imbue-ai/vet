#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

ensure_image

$RUNTIME run --rm -it \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file .env \
    "$IMAGE_NAME" bash
