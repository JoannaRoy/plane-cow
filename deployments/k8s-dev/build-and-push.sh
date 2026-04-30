#!/usr/bin/env bash
set -euo pipefail

# Build the plane-cow API image (which contains the custom cow agent code in
# apps/api/plane/cow/) and push it to the GCP Artifact Registry repo used for
# throwaway agent-testing deployments. The same image is reused by the api,
# worker, beat-worker, and migrator workloads.

PROJECT="trail-ml-9e15e"
LOCATION="europe-west1"
REPO="cow-gym-testing"
IMAGE_NAME="plane-cow-api"
# Must match planeVersion in values.yaml — the chart composes image:planeVersion.
PLANE_VERSION="v1.2.3"

REGISTRY="${LOCATION}-docker.pkg.dev/${PROJECT}/${REPO}"
IMAGE="${REGISTRY}/${IMAGE_NAME}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTEXT="${REPO_ROOT}/apps/api"
DOCKERFILE="${CONTEXT}/Dockerfile.api"

GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD)"

echo "Building ${IMAGE}:${PLANE_VERSION} (also :${GIT_SHA}, :latest)"
echo "Context : ${CONTEXT}"
echo "Platform: linux/amd64 (GKE nodes)"

docker buildx build \
  --platform linux/amd64 \
  --file "${DOCKERFILE}" \
  --tag "${IMAGE}:${PLANE_VERSION}" \
  --tag "${IMAGE}:${GIT_SHA}" \
  --tag "${IMAGE}:latest" \
  --push \
  "${CONTEXT}"

echo "Pushed ${IMAGE}:${PLANE_VERSION}"
