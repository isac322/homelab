#!/usr/bin/env bash
# Print the VA48 build revision: the number of commits in the current git
# history that changed a build input (Dockerfile or build.sh).
#
# The revision becomes the package version suffix (`+isacva48.<rev>`) and part
# of the release tag, so every merged change to the build produces a new
# release whose packages outrank the previous build of the same RPi source.
# Requires full git history; a shallow clone undercounts.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ "$(git -C "$SCRIPT_DIR" rev-parse --is-shallow-repository)" = "true" ]; then
  echo "revision.sh: shallow clone, cannot count build-input commits" >&2
  exit 1
fi

git -C "$SCRIPT_DIR" rev-list --count HEAD -- Dockerfile build.sh
