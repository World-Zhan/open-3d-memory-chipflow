#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORFS="${ROOT}/upstream/orfs-research"

cd "${ORFS}"
./build_openroad.sh \
  --local \
  --no_init \
  --threads 6 \
  --openroad-args "-D LINK_TIME_OPTIMIZATION=OFF"

test -x tools/install/OpenROAD/bin/openroad
test -x tools/install/OpenROAD/bin/sta
test -x tools/install/yosys/bin/yosys
echo "[PASS] ORFS tools installed under ${ORFS}/tools/install"
