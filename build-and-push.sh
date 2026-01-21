#!/bin/bash
set -e

REGISTRY="repo.survey-it.dk"
IMAGE_NAME="stakeholder-platform/releases-mcp"

# Read version from version.py if no tag is provided
if [ -z "$1" ]; then
    TAG=$(python3 -c "import sys; sys.path.insert(0, '.'); from version import __version__; print(__version__)")
    echo "Using version from version.py: ${TAG}"
else
    TAG="$1"
    echo "Using provided tag: ${TAG}"
fi

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "Building image: ${FULL_IMAGE}"
docker build -t "${FULL_IMAGE}" .

echo "Pushing image: ${FULL_IMAGE}"
docker push "${FULL_IMAGE}"

echo "Done! Image pushed to ${FULL_IMAGE}"
