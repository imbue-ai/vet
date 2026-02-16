#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_PATTERN="verify-everything-*-any.pkg.tar.zst"
DEBUG_PATTERN="verify-everything-debug-*-any.pkg.tar.zst"
CONTAINER_NAME="vet-pkgbuild-test-$$"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

pkg_file=$(find "$SCRIPT_DIR" -maxdepth 1 -name "$PKG_PATTERN" ! -name "$DEBUG_PATTERN" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

if [[ -z "$pkg_file" ]]; then
    echo "No package found matching $PKG_PATTERN — run 'makepkg -sf' first"
    exit 1
fi

docker run --name "$CONTAINER_NAME" -d -v "$SCRIPT_DIR":/pkg:ro archlinux:base sleep 300 >/dev/null 2>&1

run() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

run "pacman -Syu --noconfirm" >/dev/null 2>&1
run "pacman -U --noconfirm /pkg/$(basename "$pkg_file")" >/dev/null 2>&1

run "command -v vet"
run "vet --help" >/dev/null
run "vet --version"

run "
    mkdir /tmp/testrepo && cd /tmp/testrepo &&
    git init -q &&
    git config user.email test@test.com &&
    git config user.name Test &&
    echo hello > file.txt &&
    git add . && git commit -q -m init &&
    echo world >> file.txt &&
    vet --list-issue-codes >/dev/null
"

run "pacman -R --noconfirm verify-everything" >/dev/null 2>&1

if run "command -v vet" 2>/dev/null; then
    echo "FAIL: vet still found after uninstall"
    exit 1
fi

if run "test -d /opt/verify-everything"; then
    echo "FAIL: /opt/verify-everything still exists after uninstall"
    exit 1
fi
