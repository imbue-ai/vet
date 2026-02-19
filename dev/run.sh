#!/bin/bash

IMAGE_NAME="vet"

if [ "$1" = "claude" ]; then
    IMAGE_NAME="vet-claude"
fi

[ -f .env ] || { echo '.env file not found, please create one before proceeding'; exit 1; }

sudo docker run -it \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file .env \
    "$IMAGE_NAME" bash
