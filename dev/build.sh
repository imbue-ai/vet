#!/bin/bash

INSTALL_CLAUDE=false
IMAGE_NAME="vet"

if [ "$1" = "claude" ]; then
    INSTALL_CLAUDE=true
    IMAGE_NAME="vet-claude"
fi

if command -v podman &> /dev/null; then
    RUNTIME="podman"
elif command -v docker &> /dev/null; then
    RUNTIME="docker"
else
    echo "No containerization program detected. Please install podman (preferred) or docker."
    exit 1
fi

$RUNTIME build \
    --build-arg INSTALL_CLAUDE=$INSTALL_CLAUDE \
    -t $IMAGE_NAME \
    dev/.

echo "Built '$IMAGE_NAME' image using $RUNTIME."
