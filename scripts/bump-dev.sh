#!/usr/bin/env bash
# Auto-increment the dev version number.
#   1.0.0       → 1.1.0-dev.1   (start new dev cycle)
#   1.1.0-dev.3 → 1.1.0-dev.4   (increment dev number)
#
# Usage: bash scripts/bump-dev.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CURRENT="$(cat "$REPO/ha-addon/VERSION")"

if [[ "$CURRENT" =~ ^([0-9]+\.[0-9]+\.[0-9]+)-dev\.([0-9]+)$ ]]; then
    # Already a dev version — increment the dev number
    BASE="${BASH_REMATCH[1]}"
    DEV_NUM="${BASH_REMATCH[2]}"
    NEXT="${BASE}-dev.$((DEV_NUM + 1))"
elif [[ "$CURRENT" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    # Stable version — start a new minor dev cycle
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
    NEXT="${MAJOR}.$((MINOR + 1)).0-dev.1"
else
    echo "ERROR: Unrecognized version format: $CURRENT" >&2
    exit 1
fi

bash "$REPO/scripts/bump-version.sh" "$NEXT"
