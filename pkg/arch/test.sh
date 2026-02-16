#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONTAINER_NAME="vet-pkgbuild-test-$$"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --name "$CONTAINER_NAME" -d -v "$REPO_ROOT":/repo:ro archlinux:base-devel sleep 600 >/dev/null 2>&1

run() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

run "pacman -Syu --noconfirm python git" >/dev/null 2>&1

run "
    useradd -m builder &&
    mkdir /build && cp /repo/pkg/arch/PKGBUILD /repo/pkg/arch/verify-everything.install /build/ &&

    tar -czf /build/vet-current.tar.gz -C /repo --transform='s,^\.,vet-current,' \
        --exclude='.git' --exclude='pkg/arch/test.sh' . &&

    sed -i 's|^source=.*|source=(\"vet-current.tar.gz\")|' /build/PKGBUILD &&
    sed -i 's|\$srcdir/vet-\$pkgver|\$srcdir/vet-current|' /build/PKGBUILD &&

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
