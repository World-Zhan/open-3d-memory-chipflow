#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${FLOW_RUN_DIR:-}" || -z "${FLOW_STAGE:-}" ]]; then
  echo "[ERROR] use this script through scripts/run_stage.py or make" >&2
  exit 2
fi

FINAL_GDS="${ROOT}/upstream/croc/klayout/out/croc.filled.gds.gz"
LVS_GDS="${ROOT}/upstream/croc/klayout/out/croc.gds.gz"
ODB="${ROOT}/upstream/croc/openroad/out/croc.odb"
for required in "${FINAL_GDS}" "${LVS_GDS}" "${ODB}"; do
  if [[ ! -s "${required}" ]]; then
    echo "[ERROR] required signoff input is missing: ${required}" >&2
    exit 2
  fi
done

IMAGE_REF="$(python3 "${ROOT}/scripts/verify_container_lock.py" --print-ref)"
SIGNOFF_REL="signoff${FLOW_ATTEMPT_SUFFIX:-}"
SIGNOFF_DIR="${FLOW_RUN_DIR}/${SIGNOFF_REL}"
DRC_DIR="${SIGNOFF_DIR}/drc"
LVS_DIR="${SIGNOFF_DIR}/lvs"
mkdir -p "${DRC_DIR}" "${LVS_DIR}"

PDK_REL="upstream/ihp-open-pdk/ihp-sg13g2"
STD_CDL="/work/${PDK_REL}/libs.ref/sg13g2_stdcell/cdl/sg13g2_stdcell.cdl"
IO_CDL="/work/${PDK_REL}/libs.ref/sg13g2_io/cdl/sg13g2_io.cdl"
SRAM_CDL="/work/${PDK_REL}/libs.ref/sg13g2_sram/cdl/RM_IHPSG13_1P_512x32_c2_bm_bist.cdl"
BONDPAD_CDL="/work/scripts/cdl/bondpad_70x70.cdl"
CDL_OUT="/work/runs/${FLOW_RUN_ID}/${SIGNOFF_REL}/croc.cdl"

docker run --rm --user "$(id -u):$(id -g)" --entrypoint /bin/bash \
  -e HOME=/tmp \
  -e CROC_ODB=/work/upstream/croc/openroad/out/croc.odb \
  -e CROC_CDL_OUT="${CDL_OUT}" \
  -e "CROC_CDL_MASTERS=${STD_CDL}|${IO_CDL}|${SRAM_CDL}|${BONDPAD_CDL}" \
  -v "${ROOT}:/work" -w /work "${IMAGE_REF}" \
  -lc 'openroad -exit /work/scripts/write_croc_cdl.tcl'

test -s "${SIGNOFF_DIR}/croc.cdl"

set +e
docker run --rm --user "$(id -u):$(id -g)" --entrypoint /bin/bash \
  -e HOME=/tmp -v "${ROOT}:/work" -w /work "${IMAGE_REF}" -lc \
  "python3 /work/${PDK_REL}/libs.tech/klayout/tech/drc/run_drc.py \
    --path /work/upstream/croc/klayout/out/croc.filled.gds.gz \
    --topcell croc_chip_sealed --run_dir /work/runs/${FLOW_RUN_ID}/${SIGNOFF_REL}/drc \
    --run_mode deep --mp 6 --density_thr 6 --antenna"
DRC_RC=$?

docker run --rm --user "$(id -u):$(id -g)" --entrypoint /bin/bash \
  -e HOME=/tmp -v "${ROOT}:/work" -w /work "${IMAGE_REF}" -lc \
  "python3 /work/${PDK_REL}/libs.tech/klayout/tech/lvs/run_lvs.py \
    --layout /work/upstream/croc/klayout/out/croc.gds.gz \
    --netlist ${CDL_OUT} --topcell croc_chip \
    --run_dir /work/runs/${FLOW_RUN_ID}/${SIGNOFF_REL}/lvs --run_mode flat"
LVS_RC=$?
set -e

python3 "${ROOT}/scripts/parse_croc_signoff.py" \
  --signoff-dir "${SIGNOFF_DIR}" --drc-returncode "${DRC_RC}" --lvs-returncode "${LVS_RC}"
