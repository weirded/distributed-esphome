#!/usr/bin/env bash
# Bump the version number in all three places that must stay in sync:
#   1. ha-addon/VERSION           (read by server at runtime)
#   2. ha-addon/config.yaml       (required by HA add-on manifest)
#   3. client/client.py           (CLIENT_VERSION constant)
#
# Usage: bash scripts/bump-version.sh X.Y.Z
set -euo pipefail

VERSION="${1:?Usage: $0 X.Y.Z}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "$VERSION" > "$REPO/ha-addon/VERSION"

# config.yaml — version: "X.Y.Z"
sed -i.bak "s/^version: .*/version: \"$VERSION\"/" "$REPO/ha-addon/config.yaml"
rm -f "$REPO/ha-addon/config.yaml.bak"

# client.py — CLIENT_VERSION = "X.Y.Z"
sed -i.bak "s/^CLIENT_VERSION = .*/CLIENT_VERSION = \"$VERSION\"/" "$REPO/client/client.py"
rm -f "$REPO/client/client.py.bak"

echo "Bumped to $VERSION in:"
echo "  ha-addon/VERSION"
echo "  ha-addon/config.yaml"
echo "  client/client.py"
echo ""
echo "Next: bash scripts/sync-client.sh  (syncs client/ → ha-addon/client/)"
