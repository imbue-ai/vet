#!/bin/bash

IMAGE_NAME="vet"

if command -v podman &> /dev/null; then
    RUNTIME="podman"
elif command -v docker &> /dev/null; then
    RUNTIME="docker"
else
    echo "No containerization program detected. Please install podman (preferred) or docker."
    exit 1
fi

if [ "$1" = "claude" ]; then
    IMAGE_NAME="vet-claude"
fi

[ -f .env ] || { echo '.env file not found, please create one before proceeding'; exit 1; }

$RUNTIME run --rm -it \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file .env \
    "$IMAGE_NAME" bash
