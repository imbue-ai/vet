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

[ -f .env ] || { echo '.env file not found, please create one before proceeding'; exit 1; }
set -a; source .env; set +a

IMAGE_NAME="vet"
INSTALL_CLAUDE="false"
if [ "${I_CHOOSE_CONVENIENCE_OVER_FREEDOM:-}" = "true" ]; then
    IMAGE_NAME="vet-claude"
    INSTALL_CLAUDE="true"
fi
