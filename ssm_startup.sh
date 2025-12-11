#!/usr/bin/env bash
# Helper to switch to the ubuntu user and rebuild/redeploy the odds-price-alert app.
# Intended for use in AWS SSM Session Manager bash sessions.
# Usage: `bash ssm_startup.sh`

set -euo pipefail

TARGET_USER="ubuntu"
PROJECT_DIR="/home/${TARGET_USER}/odds-price-alert"

run_commands() {
  set -euo pipefail

  if [ ! -d "${PROJECT_DIR}" ]; then
    echo "Project directory ${PROJECT_DIR} not found." >&2
    exit 1
  fi

  cd "${PROJECT_DIR}"

  echo "Building odds-price-alert image..."
  docker build -t odds-price-alert .

  echo "Stopping existing containers (if any)..."
  existing_containers="$(docker ps -aq)"
  if [ -n "${existing_containers}" ]; then
    docker stop ${existing_containers}
    docker rm ${existing_containers}
  else
    echo "No containers to stop/remove."
  fi

  echo "Running deploy script..."
  ./deploy_on_ec2.sh
}

if [ "$(whoami)" = "${TARGET_USER}" ]; then
  run_commands
else
  echo "Switching to ${TARGET_USER} user..."
  sudo -i -u "${TARGET_USER}" bash -c "$(declare -f run_commands); run_commands"
fi
