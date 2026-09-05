#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAIWEI="${ROOT}/upstream/taiwei-pin-3d"
PATCH="${ROOT}/patches/taiwei-pin-3d/0001-tech-derived-hbt-capacity-contract.patch"
MODE="${1:-check}"
PATCH_APPLIED=0

if [[ "${MODE}" != "check" && "${MODE}" != "run" ]]; then
  echo "usage: $0 check | run <command> [args...]" >&2
  exit 2
fi
if [[ ! -d "${TAIWEI}/.git" && ! -f "${TAIWEI}/.git" ]]; then
  echo "[ERROR] pinned TaiWei submodule is unavailable: ${TAIWEI}" >&2
  exit 2
fi
if [[ ! -f "${PATCH}" ]]; then
  echo "[ERROR] missing HBT contract patch: ${PATCH}" >&2
  exit 2
fi
if [[ -n "$(git -C "${TAIWEI}" status --porcelain --untracked-files=no)" ]]; then
  echo "[ERROR] pinned TaiWei source is dirty; review it before applying the contract patch" >&2
  exit 2
fi

git -C "${TAIWEI}" apply --check "${PATCH}"
echo "[PATCH] check passed: ${PATCH}"
if [[ "${MODE}" == "check" ]]; then
  exit 0
fi
shift
if [[ $# -eq 0 ]]; then
  echo "[ERROR] run mode requires a command" >&2
  exit 2
fi

cleanup() {
  local rc=$?
  trap - EXIT HUP INT TERM
  if [[ ${PATCH_APPLIED} -eq 1 ]]; then
    if git -C "${TAIWEI}" apply --reverse --check "${PATCH}"; then
      git -C "${TAIWEI}" apply --reverse "${PATCH}"
      echo "[PATCH] restored pinned TaiWei source"
    else
      echo "[ERROR] cannot restore TaiWei HBT contract patch automatically" >&2
      rc=3
    fi
  fi
  exit "${rc}"
}
trap cleanup EXIT HUP INT TERM

git -C "${TAIWEI}" apply "${PATCH}"
PATCH_APPLIED=1
"$@"
