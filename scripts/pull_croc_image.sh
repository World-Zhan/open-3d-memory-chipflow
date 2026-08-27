#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="hpretl/iic-osic-tools:2025.12"
FALLBACK="docker.1ms.run/hpretl/iic-osic-tools@sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521"
FALLBACK_DIGEST="sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521"

pull_with_retries() {
  local source="$1"
  local attempt
  for attempt in 1 2 3 4 5 6; do
    echo "[PULL] source=${source} attempt=${attempt}/6"
    if docker pull "${source}"; then
      return 0
    fi
    sleep 3
  done
  return 1
}

SOURCE="${IMAGE}"
if ! timeout 90s docker pull "${IMAGE}"; then
  echo "[WARN] Docker Hub is unavailable; using the lock-file fallback by OCI digest." >&2
  SOURCE="${FALLBACK}"
  pull_with_retries "${SOURCE}"
fi

if [[ "${SOURCE}" == "${FALLBACK}" ]]; then
  DIGEST="${FALLBACK_DIGEST}"
else
  REPO_DIGEST="$(docker image inspect "${SOURCE}" --format '{{index .RepoDigests 0}}')"
  DIGEST="${REPO_DIGEST##*@}"
fi

docker tag "${SOURCE}" "${IMAGE}"
IMAGE_ID="$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
python3 "${ROOT}/scripts/record_container_digest.py" \
  --reference "${IMAGE}" --source-reference "${SOURCE}" \
  --digest "${DIGEST}" --image-id "${IMAGE_ID}"
