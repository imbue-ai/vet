#!/bin/bash

IMAGE_NAME="vet"

if [ "$1" = "claude" ]; then
    IMAGE_NAME="vet-claude"
fi

[ -f .env ] || { echo '.env file not found, please create one before proceeding'; exit 1; }

GIT_USER_NAME=$(git config user.name 2>/dev/null || echo "")
GIT_USER_EMAIL=$(git config user.email 2>/dev/null || echo "")

docker run -it \
    --mount type=bind,source="$(pwd)",target=/app \
    --env-file .env \
    -e GIT_AUTHOR_NAME="$GIT_USER_NAME" \
    -e GIT_AUTHOR_EMAIL="$GIT_USER_EMAIL" \
    -e GIT_COMMITTER_NAME="$GIT_USER_NAME" \
    -e GIT_COMMITTER_EMAIL="$GIT_USER_EMAIL" \
    "$IMAGE_NAME" bash
