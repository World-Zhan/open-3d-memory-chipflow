#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORFS="${ROOT}/upstream/orfs-research"
THREADS="${ORFS_BUILD_THREADS:-6}"

if [[ ! "${THREADS}" =~ ^[1-6]$ ]]; then
  echo "[ERROR] ORFS_BUILD_THREADS must be an integer from 1 through 6." >&2
  exit 1
fi

submodule_status="$(git -C "${ROOT}" submodule status --recursive)"
if grep -qE '^[+-]' <<<"${submodule_status}"; then
  echo "[ERROR] ORFS submodules are missing or do not match the locked commits." >&2
  echo "[ERROR] Run 'make init-submodules' and retry." >&2
  exit 1
fi

export PATH="${ROOT}/scripts/download-shims:${PATH}"
if command -v aria2c >/dev/null 2>&1; then
  echo "[INFO] GitHub assets use the finite-retry aria2 download shim."
else
  echo "[WARN] aria2c is unavailable; dependency downloads fall back to system wget." >&2
fi

echo "[INFO] ORFS base packages use sudo; prefix dependencies remain owned by $(id -un)."
sudo "${ORFS}/etc/DependencyInstaller.sh" -base
"${ORFS}/etc/DependencyInstaller.sh" -common -threads="${THREADS}" -prefix="${ORFS}/dependencies"
