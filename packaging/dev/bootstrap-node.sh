#!/bin/sh
# Downloads a pinned Node.js build into ~/.local/node and symlinks
# node/npm/npx/corepack into ~/.local/bin, for boxes with no passwordless
# sudo to `dnf install nodejs npm` (PLAN.md §10). Safe to re-run.
set -eu

NODE_VERSION=v22.23.2

ARCH=$(uname -m)
case "$ARCH" in
  x86_64) NODE_ARCH=x64 ;;
  aarch64) NODE_ARCH=arm64 ;;
  *)
    echo "bootstrap-node: unsupported architecture: $ARCH" >&2
    exit 1
    ;;
esac

FILE="node-${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
BASE_URL="https://nodejs.org/dist/${NODE_VERSION}"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

echo "Downloading ${FILE}..."
curl -fsSL -o "$WORKDIR/$FILE" "${BASE_URL}/${FILE}"
curl -fsSL -o "$WORKDIR/SHASUMS256.txt" "${BASE_URL}/SHASUMS256.txt"

echo "Verifying checksum..."
(cd "$WORKDIR" && grep " ${FILE}\$" SHASUMS256.txt | sha256sum -c -)

rm -rf "$HOME/.local/node"
mkdir -p "$HOME/.local/node"
tar -xJf "$WORKDIR/$FILE" -C "$HOME/.local/node" --strip-components=1

mkdir -p "$HOME/.local/bin"
for bin in node npm npx corepack; do
  if [ -e "$HOME/.local/node/bin/$bin" ]; then
    ln -sf "$HOME/.local/node/bin/$bin" "$HOME/.local/bin/$bin"
  fi
done

echo "Node $("$HOME/.local/bin/node" --version) ready. Make sure \$HOME/.local/bin is on your PATH."
