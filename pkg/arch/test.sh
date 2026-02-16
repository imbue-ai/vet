#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="vet-pkgbuild-test-$$"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --name "$CONTAINER_NAME" -d -v "$SCRIPT_DIR":/repo:ro archlinux:base-devel sleep 600 >/dev/null 2>&1

run() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

run "pacman -Syu --noconfirm python git" >/dev/null 2>&1

run "
    useradd -m builder &&
    mkdir /build && cp /repo/PKGBUILD /repo/verify-everything.install /build/ &&
    chown -R builder:builder /build
"

run "su - builder -c 'cd /build && makepkg -sf --noconfirm'" >/dev/null 2>&1

run "pacman -U --noconfirm /build/verify-everything-*-any.pkg.tar.zst" >/dev/null 2>&1

run "command -v vet"
run "vet --help" >/dev/null
run "vet --version"
run "vet --list-issue-codes" >/dev/null

run "pacman -R --noconfirm verify-everything" >/dev/null 2>&1

if run "command -v vet" 2>/dev/null; then
    echo "FAIL: vet still found after uninstall"
    exit 1
fi

if run "test -d /opt/verify-everything"; then
    echo "FAIL: /opt/verify-everything still exists after uninstall"
    exit 1
fi
