#!/usr/bin/env bash
# Build the pinned, unmodified upstream HAPI Hub and PWA.
set -euo pipefail

HAPI_REPOSITORY="https://github.com/tiann/hapi.git"
HAPI_VERSION="v0.30.7"
HAPI_COMMIT="0239edf38e2da653d662f31039e24ccea04c7837"
BUN_VERSION="1.4.0"

if [[ $# != 1 ]]; then
  echo "Usage: build-hapi.sh <managed-checkout-directory>" >&2
  exit 2
fi

CHECKOUT_DIR="$1"

command -v git >/dev/null
command -v bun >/dev/null

if [[ "$(bun --version)" != "$BUN_VERSION" ]]; then
  echo "Bun $BUN_VERSION is required" >&2
  exit 2
fi

if [[ ! -e "$CHECKOUT_DIR" ]]; then
  git clone --filter=blob:none --no-checkout "$HAPI_REPOSITORY" "$CHECKOUT_DIR"
  git -C "$CHECKOUT_DIR" config --local agent-container.managed true
elif [[ ! -d "$CHECKOUT_DIR/.git" ]] || \
     [[ "$(git -C "$CHECKOUT_DIR" config --local --get agent-container.managed || true)" != true ]]; then
  echo "Refusing to replace a directory not created by this script: $CHECKOUT_DIR" >&2
  exit 2
fi

git -C "$CHECKOUT_DIR" remote set-url origin "$HAPI_REPOSITORY"
git -C "$CHECKOUT_DIR" fetch --force --filter=blob:none origin \
  "refs/tags/$HAPI_VERSION:refs/tags/$HAPI_VERSION"

TAG_COMMIT="$(git -C "$CHECKOUT_DIR" rev-list -n 1 "$HAPI_VERSION")"
if [[ "$TAG_COMMIT" != "$HAPI_COMMIT" ]]; then
  echo "HAPI tag $HAPI_VERSION does not resolve to the pinned commit" >&2
  exit 1
fi

# CHECKOUT_DIR is script-owned, so each build starts from the verified upstream tree.
git -C "$CHECKOUT_DIR" reset --hard "$HAPI_COMMIT"
git -C "$CHECKOUT_DIR" clean -fdx

(
  cd "$CHECKOUT_DIR"
  bun install --frozen-lockfile
  bun run --cwd web typecheck
  bun run --cwd web build
  bun run --cwd hub generate:embedded-web-assets
  bun run --cwd hub build
)

test -s "$CHECKOUT_DIR/hub/dist/index.js"
echo "Built HAPI $HAPI_VERSION at $CHECKOUT_DIR/hub/dist/index.js"
