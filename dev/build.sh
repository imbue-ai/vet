#!/bin/bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

$RUNTIME build \
    --build-arg INSTALL_CLAUDE="$INSTALL_CLAUDE" \
    -f "$SCRIPT_DIR/Containerfile" \
    -t "$IMAGE_NAME" \
    "$SCRIPT_DIR/."
