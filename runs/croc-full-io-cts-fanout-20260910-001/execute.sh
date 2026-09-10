set -e
source /work/upstream/croc/env.sh
openroad -exit /output/edit.tcl
openroad -exit /output/check.tcl
