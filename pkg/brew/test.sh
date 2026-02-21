#!/usr/bin/env bash
set -euo pipefail

# builds Homebrew formula from working tree, installs it, runs a few non-llm vet commands, tests uninstall

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

FORMULA="$SCRIPT_DIR/verify-everything.rb"

# patch the formula to point at the local working tree instead of PyPI
PATCHED_FORMULA="$(mktemp)"
cleanup() {
    rm -f "$PATCHED_FORMULA"
}
trap cleanup EXIT

sed \
    -e "s|^  url \"https://files.pythonhosted.org/.*|  url \"file://$REPO_ROOT\"|" \
    -e '/^  sha256/d' \
    "$FORMULA" > "$PATCHED_FORMULA"

# build + install from source
brew install --build-from-source --formula "$PATCHED_FORMULA"

# basic non-llm commands
command -v vet
vet --help
vet --version
vet --list-issue-codes

# uninstall
brew uninstall verify-everything

if command -v vet 2>/dev/null; then
    echo "FAIL: vet still found after uninstall"
    exit 1
fi
