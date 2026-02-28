#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if command -v podman &> /dev/null; then
    RUNTIME="podman"
elif command -v docker &> /dev/null; then
    RUNTIME="docker"
else
    echo "No containerization program detected. Please install podman (preferred) or docker."
    exit 1
fi

[ -f "$REPO_ROOT/.env" ] || { echo '.env file not found, please create one before proceeding'; exit 1; }
set -a; source "$REPO_ROOT/.env"; set +a

IMAGE_NAME="vet"
INSTALL_CLAUDE="false"

# Everything in dev/ runs inside ephemeral containers, so grant OpenCode full
# permissions (no interactive prompts). Without this, non-interactive
# `opencode run` auto-rejects any "ask" permission (e.g. external_directory).
OPENCODE_PERMISSION='{"*":"allow","external_directory":{"*":"allow"}}'
if [ "${I_CHOOSE_CONVENIENCE_OVER_FREEDOM:-}" = "true" ]; then
    IMAGE_NAME="vet-nonfree"
    INSTALL_CLAUDE="true"

    RED='\033[1;31m'
    NC='\033[0m'
    echo -e "${RED}" >&2
    echo "WARNING: You are building an image that includes proprietary software." >&2
    echo "" >&2
    echo "By proceeding, you have chosen to surrender your freedom to a" >&2
    echo "corporation that does not respect your rights as a user. The" >&2
    echo "proprietary components included in this image may restrict your" >&2
    echo "ability to study, modify, and share the software you run." >&2
    echo "" >&2
    echo "This is not merely a technical decision, it is an ethical one." >&2
    echo "Every time you run proprietary software, you give up control over" >&2
    echo "your own computing. You deserve better." >&2
    echo "" >&2
    echo "Proceeding anyway... We shall assume you are testing, not using the software." >&2
    echo -e "${NC}" >&2
fi
