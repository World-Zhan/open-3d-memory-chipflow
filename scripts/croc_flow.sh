#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CROC="${ROOT}/upstream/croc"
IHP_PDK="${ROOT}/upstream/ihp-open-pdk/ihp-sg13g2"
STAGE="${1:-}"

if [[ -z "${FLOW_RUN_DIR:-}" || -z "${FLOW_STAGE:-}" ]]; then
  echo "[ERROR] use this script through scripts/run_stage.py or make" >&2
  exit 2
fi

python3 "${ROOT}/scripts/verify_container_lock.py"

croc_container() {
  local payload="$1"
  cd "${CROC}"
  env UID="$(id -u)" GID="$(id -g)" docker compose run --rm -T \
    -v "${ROOT}/scripts:/flow-scripts:ro" \
    -v "${IHP_PDK}:/fosic/designs/croc/ihp13/pdk/ihp-sg13g2:ro" \
    -e CROC_PDK=sg13g2 -e VERILATOR_JOBS=6 \
    pulp-docker --skip bash -lc "${payload}"
}

archive_stage() {
  local label="$1"
  shift
  local args=(--label "${label}" --allow-missing)
  local item
  for item in "$@"; do
    args+=(--path "${item}")
  done
  python3 "${ROOT}/scripts/snapshot.py" "${args[@]}"
}

run_and_capture() {
  local payload="$1"
  shift
  set +e
  croc_container "${payload}"
  local tool_rc=$?
  set -e
  archive_stage "${STAGE}${FLOW_ATTEMPT_SUFFIX:-}" "$@"
  local evidence_rc=0
  python3 "${ROOT}/scripts/collect_croc_evidence.py" "${STAGE}" || evidence_rc=$?
  if [[ ${tool_rc} -ne 0 ]]; then
    return "${tool_rc}"
  fi
  return "${evidence_rc}"
}

case "${STAGE}" in
  rtl)
    run_and_capture \
      'cd sw && make all && cd ../verilator && ./run_verilator.sh --build --run ../sw/bin/helloworld.hex' \
      upstream/croc/sw/bin upstream/croc/verilator/build upstream/croc/verilator/logs
    ;;
  netlist-sim)
    run_and_capture \
      'cd yosys && ./run_synthesis.sh --synth && cd ../verilator && ./run_verilator.sh --build-netlist --run-netlist ../sw/bin/helloworld.hex' \
      upstream/croc/yosys/out upstream/croc/yosys/reports upstream/croc/yosys/croc.log \
      upstream/croc/verilator/build-netlist upstream/croc/verilator/logs
    ;;
  pnr)
    if [[ ! -s "${CROC}/yosys/out/croc_yosys.v" ]]; then
      echo "[INFO] synthesis output is absent; running synthesis prerequisite"
      croc_container 'cd yosys && ./run_synthesis.sh --synth'
    fi
    run_and_capture \
      'cd openroad && ./run_backend.sh --all && CROC_ODB=/fosic/designs/croc/openroad/out/croc.odb CROC_ACCEPTANCE_REPORT=/fosic/designs/croc/openroad/reports/open3d_acceptance.rpt openroad -exit /flow-scripts/check_croc_final.tcl' \
      upstream/croc/openroad/out upstream/croc/openroad/reports upstream/croc/openroad/logs upstream/croc/openroad/save
    ;;
  gds)
    if [[ ! -s "${CROC}/openroad/out/croc.def" ]]; then
      echo "[ERROR] croc-pnr must complete before croc-gds" >&2
      exit 2
    fi
    run_and_capture \
      'export PATH=/flow-scripts/download-shims:$PATH; cd klayout && ./run_finishing.sh --gds --seal --fill' \
      upstream/croc/klayout/out
    ;;
  *)
    echo "usage: $0 {rtl|netlist-sim|pnr|gds}" >&2
    exit 2
    ;;
esac
