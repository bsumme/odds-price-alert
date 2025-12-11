#!/usr/bin/env bash
# Rebuild and run the combined FastAPI + static frontend image on EC2.
# - Cleans up old containers/images for this app
# - Builds the single-container image from the current checkout
# - Starts it with the provided THE_ODDS_API_KEY and publishes port 8000 (or APP_PORT override)

set -euo pipefail

IMAGE_NAME=${IMAGE_NAME:-odds-price-alert}
CONTAINER_NAME=${CONTAINER_NAME:-odds-price-alert}
APP_PORT=${APP_PORT:-8000}

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

if [[ -z "${THE_ODDS_API_KEY:-}" ]]; then
  echo "[ERROR] THE_ODDS_API_KEY is not set. Export your Odds API key before running." >&2
  exit 1
fi

log "Stopping and removing any existing container named ${CONTAINER_NAME}..."
docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | xargs -r docker rm -f

log "Removing old images tagged ${IMAGE_NAME} (if any)..."
# Remove all tags for the image name to avoid orphaned layers while preserving other project images.
mapfile -t old_tags < <(docker images "${IMAGE_NAME}" --format '{{.Repository}}:{{.Tag}}')
if [[ ${#old_tags[@]} -gt 0 ]]; then
  docker rmi -f "${old_tags[@]}" || true
else
  log "No existing images found for ${IMAGE_NAME}."
fi

log "Pruning dangling images to free disk space..."
docker image prune -f >/dev/null

log "Building a fresh image (${IMAGE_NAME})..."
docker build --pull -t "${IMAGE_NAME}" .

log "Starting container ${CONTAINER_NAME} on port ${APP_PORT}..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  -p "${APP_PORT}:8000" \
  -e THE_ODDS_API_KEY="${THE_ODDS_API_KEY}" \
  "${IMAGE_NAME}"

log "Deployment complete. Access the app at http://<your-public-ip>:${APP_PORT}"
