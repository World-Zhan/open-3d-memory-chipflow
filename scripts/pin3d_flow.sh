#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN3D="${ROOT}/upstream/taiwei-pin-3d"
ORFS="${ROOT}/upstream/orfs-research"
MODE="${1:-}"

if [[ "${MODE}" != "smoke" && "${MODE}" != "full" ]]; then
  echo "usage: $0 {smoke|full}" >&2
  exit 2
fi
if [[ -z "${FLOW_RUN_DIR:-}" || -z "${FLOW_STAGE:-}" ]]; then
  echo "[ERROR] use this script through scripts/run_stage.py or make" >&2
  exit 2
fi
for tool in "${ORFS}/tools/install/OpenROAD/bin/openroad" "${ORFS}/tools/install/OpenROAD/bin/sta" "${ORFS}/tools/install/yosys/bin/yosys"; do
  if [[ ! -x "${tool}" ]]; then
    echo "[ERROR] ORFS tool is missing: ${tool}; run make orfs-deps and make orfs-build" >&2
    exit 2
  fi
done

export ORFS_DIR="${ORFS}"
export OPENROAD_EXE="${ORFS}/tools/install/OpenROAD/bin/openroad"
export STA_EXE="${ORFS}/tools/install/OpenROAD/bin/sta"
export YOSYS_EXE="${ORFS}/tools/install/yosys/bin/yosys"
export NUM_CORES=6
export FLOW_VARIANT=openroad

cd "${PIN3D}"
set +e
python3 run_experiments.py --flow ord --tech asap7_3D --case gcd --jobs 1 --run-only
TOOL_RC=$?

if [[ ${TOOL_RC} -eq 0 && "${MODE}" == "full" ]]; then
  HOTSPOT_DIR="${ROOT}/upstream/open3dflow/HotSpot"
  if [[ ! -f "${HOTSPOT_DIR}/scripts/divide_def.py" || ! -f "${HOTSPOT_DIR}/examples/thermal/run.sh" ]]; then
    echo "[ERROR] TaiWei ord-hotspot requires a HotSpot harness not included in its pinned release: ${HOTSPOT_DIR}" >&2
    TOOL_RC=3
  else
    HOTSPOT_SCRIPTS_DIR="${HOTSPOT_DIR}" bash test/common/run_stage.sh asap7_3D openroad openroad gcd ord-hotspot
    TOOL_RC=$?
  fi
fi
set -e

python3 "${ROOT}/scripts/snapshot.py" --label "pin3d-${MODE}${FLOW_ATTEMPT_SUFFIX:-}" --allow-missing \
  --path upstream/taiwei-pin-3d/results/asap7_3D/gcd/openroad \
  --path upstream/taiwei-pin-3d/reports/asap7_3D/gcd/openroad \
  --path upstream/taiwei-pin-3d/logs/asap7_3D/gcd/openroad \
  --path upstream/taiwei-pin-3d/objects/asap7_3D/gcd/openroad \
  --path upstream/taiwei-pin-3d/run_logs

python3 "${ROOT}/scripts/collect_pin3d_evidence.py" --mode "${MODE}" --tool-returncode "${TOOL_RC}"
