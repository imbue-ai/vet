#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

$RUNTIME build \
    --build-arg INSTALL_CLAUDE="$INSTALL_CLAUDE" \
    -f dev/Containerfile \
    -t "$IMAGE_NAME" \
    dev/.

echo "Built '$IMAGE_NAME' image using $RUNTIME."
