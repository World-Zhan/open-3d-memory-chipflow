#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENROAD="${ROOT}/upstream/orfs-research/tools/OpenROAD"
PATCH="${ROOT}/patches/openroad/0001-top-routing-layer-standard-cell-down-via.patch"
CMAKE="${ROOT}/upstream/orfs-research/dependencies/bin/cmake"
BUILD="${OPENROAD}/build"
BINARY="${ROOT}/upstream/orfs-research/tools/install/OpenROAD/bin/openroad"
MODE="${1:-build}"
PATCH_APPLIED=0

if [[ "${MODE}" != "build" && "${MODE}" != "check" ]]; then
  echo "usage: $0 [build|check]" >&2
  exit 2
fi
for path in "${OPENROAD}/.git" "${PATCH}" "${CMAKE}" "${BUILD}"; do
  if [[ ! -e "${path}" ]]; then
    echo "[ERROR] missing required path: ${path}" >&2
    exit 2
  fi
done

cleanup() {
  local rc=$?
  trap - EXIT HUP INT TERM
  if [[ ${PATCH_APPLIED} -eq 1 ]]; then
    if git -C "${OPENROAD}" apply --reverse --check "${PATCH}"; then
      git -C "${OPENROAD}" apply --reverse "${PATCH}"
      echo "[PATCH] restored pinned OpenROAD source"
    else
      echo "[ERROR] cannot restore OpenROAD patch automatically" >&2
      rc=3
    fi
  fi
  exit "${rc}"
}
trap cleanup EXIT HUP INT TERM

if [[ -n "$(git -C "${OPENROAD}" status --porcelain --untracked-files=no)" ]]; then
  echo "[ERROR] pinned OpenROAD source is dirty; preserve/review it before building" >&2
  exit 2
fi
git -C "${OPENROAD}" apply --check "${PATCH}"
echo "[PATCH] check passed: ${PATCH}"
if [[ "${MODE}" == "check" ]]; then
  exit 0
fi

git -C "${OPENROAD}" apply "${PATCH}"
PATCH_APPLIED=1
"${CMAKE}" --build "${BUILD}" --target install --parallel "${NUM_CORES:-6}"
"${BINARY}" -version

# The EXIT trap restores the pinned source; the installed binary intentionally
# retains the tested change and its SHA-256 must be recorded in run evidence.
