#!/bin/bash
set -e

REGISTRY="repo.survey-it.dk"
IMAGE_NAME="stakeholder-platform/releases-mcp"
TAG="${1:-latest}"

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "Building image: ${FULL_IMAGE}"
docker build -t "${FULL_IMAGE}" .

echo "Pushing image: ${FULL_IMAGE}"
docker push "${FULL_IMAGE}"

echo "Done! Image pushed to ${FULL_IMAGE}"
