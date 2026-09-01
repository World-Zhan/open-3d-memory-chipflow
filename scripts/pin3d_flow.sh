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
# Mirrored upper-tier standard-cell pins are on M1_m, which is one routing
# layer above M2_m in the ASAP7_3D LEF ordering.  The pinned upstream default
# stops at M2_m and reproducibly raises GRT-0029 during ord-place-upper.
export MAX_ROUTING_LAYER="${MAX_ROUTING_LAYER:-M1_m}"

# The pinned detail-route script otherwise adds -no_pin_access.  Keep strict
# pin access enabled and fail closed if a caller tries to restore that bypass.
export DETAILED_ROUTE_ARGS="${DETAILED_ROUTE_ARGS:--or_k 1.0 -droute_end_iter 20 -verbose 1 -drc_report_iter_step 5}"
if [[ " ${DETAILED_ROUTE_ARGS} " == *" -no_pin_access "* ]]; then
  echo "[ERROR] -no_pin_access is forbidden for Pin3D acceptance runs" >&2
  exit 2
fi

TASK_STATUS_FILE="${PIN3D}/run_logs/status/ord__asap7_3D__gcd.json"
python3 "${ROOT}/scripts/archive_pin3d_task_status.py" \
  --status-file "${TASK_STATUS_FILE}" --run-dir "${FLOW_RUN_DIR}" --label "${FLOW_STAGE_INSTANCE:-${FLOW_STAGE}}"

cd "${PIN3D}"
set +e
python3 run_experiments.py --flow ord --tech asap7_3D --case gcd --jobs 1 --run-only
TOOL_RC=$?

# The pinned scheduler returns zero after monitoring even when a detached task
# failed, so propagate the task status before collecting acceptance evidence.
python3 "${ROOT}/scripts/check_pin3d_task_status.py" \
  --status-file "${TASK_STATUS_FILE}"
TASK_RC=$?
if [[ ${TOOL_RC} -eq 0 && ${TASK_RC} -ne 0 ]]; then
  TOOL_RC=${TASK_RC}
fi

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
