#!/usr/bin/env bash
set -euo pipefail

# Usage: ./release.sh 0.2.0
#
# This script:
#   1. Updates the version in pyproject.toml
#   2. Reminds you to update CHANGELOG.md if you haven't
#   3. Commits, tags, and pushes — triggering the publish workflow

if [ $# -ne 1 ]; then
    echo "Usage: $0 <version>  (e.g. 0.2.0)"
    exit 1
fi

VERSION="$1"
TAG="v${VERSION}"

# Sanity checks
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Error: tag $TAG already exists"
    exit 1
fi

if ! grep -q "## \[${VERSION}\]" CHANGELOG.md; then
    echo ""
    echo "No entry for [${VERSION}] found in CHANGELOG.md."
    echo "Please add your changelog entry under ## [${VERSION}] before releasing."
    echo ""
    exit 1
fi

# Update version in pyproject.toml (portable across GNU and BSD sed)
sed "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml > pyproject.toml.tmp && mv pyproject.toml.tmp pyproject.toml
echo "Updated pyproject.toml to version ${VERSION}"

# Commit and tag
git add pyproject.toml CHANGELOG.md
git commit -m "release ${TAG}"
git tag -a "$TAG" -m "release ${TAG}"

echo ""
echo "Ready. Run this to publish:"
echo ""
echo "  git push origin main --tags"
echo ""
