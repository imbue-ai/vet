#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

build_image() {
    local install_claude="$1"
    local image_name="$2"

    $RUNTIME build \
        --build-arg INSTALL_CLAUDE="$install_claude" \
        -f dev/Containerfile \
        -t "$image_name" \
        dev/.

    echo "Built '$image_name' image using $RUNTIME."
}

if [ "$1" = "claude" ]; then
    build_image true vet-claude
elif [ -n "$1" ]; then
    echo "Unknown argument: $1"
    echo "Usage: ./dev/build.sh [claude]"
    exit 1
else
    build_image false vet
    build_image true vet-claude
fi
