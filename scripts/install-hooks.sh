#!/usr/bin/env bash
# Configure git to use the .githooks directory and make hooks executable.
set -euo pipefail
git config core.hooksPath .githooks
chmod +x .githooks/*
echo "Git hooks installed (core.hooksPath = .githooks)."
