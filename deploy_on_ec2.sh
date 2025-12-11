#!/usr/bin/env bash
# Rebuild and run the combined FastAPI + static frontend image on EC2.
# - Cleans up old containers/images for this app
# - Builds the single-container image from the current checkout
# - Starts it with the provided THE_ODDS_API_KEY and publishes port 8000 (or APP_PORT override)

set -euo pipefail

IMAGE_NAME=${IMAGE_NAME:-odds-price-alert}
CONTAINER_NAME=${CONTAINER_NAME:-odds-price-alert}
APP_PORT=${APP_PORT:-8000}
AUTO_FREE_APP_PORT=${AUTO_FREE_APP_PORT:-false}

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

check_port_conflicts() {
  log "Checking if host port ${APP_PORT} is free..."

  # If any running container already publishes the port, optionally stop it or abort early.
  mapfile -t port_containers < <(docker ps --filter "publish=${APP_PORT}" --format '{{.ID}} {{.Names}} ({{.Ports}})')
  if [[ ${#port_containers[@]} -gt 0 ]]; then
    if [[ "${AUTO_FREE_APP_PORT,,}" == "true" ]]; then
      log "AUTO_FREE_APP_PORT=true; stopping and removing container(s) using port ${APP_PORT}:"
      for entry in "${port_containers[@]}"; do
        # Extract the first field (container ID) before any space-delimited name/port info.
        container_id=${entry%% *}
        log "- docker stop ${container_id} && docker rm ${container_id}"
        docker stop "${container_id}" >/dev/null && docker rm "${container_id}" >/dev/null
      done
    else
      echo "[ERROR] Port ${APP_PORT} is already in use by container(s):" >&2
      printf '  %s\n' "${port_containers[@]}" >&2
      echo "Resolve by running: docker ps --filter \"publish=${APP_PORT}\" --format '{{.ID}} {{.Names}} ({{.Ports}})'" >&2
      echo "Then stop/remove them (e.g., docker stop <id> && docker rm <id>) or rerun with APP_PORT=<free_port>." >&2
      echo "To stop them automatically, rerun with AUTO_FREE_APP_PORT=true." >&2
      exit 1
    fi
  fi

  # Detect non-Docker listeners (useful if a host process already binds the port).
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn "sport = :${APP_PORT}" | tail -n +2 | grep -q .; then
      echo "[ERROR] Port ${APP_PORT} is already bound by a host process (non-Docker)." >&2
      echo "Check with: sudo ss -ltnp 'sport = :${APP_PORT}'" >&2
      if command -v lsof >/dev/null 2>&1; then
        echo "Or: sudo lsof -iTCP:${APP_PORT} -sTCP:LISTEN" >&2
      fi
      echo "Stop that process or rerun with APP_PORT=<free_port>." >&2
      exit 1
    fi
  fi
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

check_port_conflicts

log "Starting container ${CONTAINER_NAME} on port ${APP_PORT}..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  -p "${APP_PORT}:8000" \
  -e THE_ODDS_API_KEY="${THE_ODDS_API_KEY}" \
  "${IMAGE_NAME}"

log "Deployment complete. Access the app at http://<your-public-ip>:${APP_PORT}"
