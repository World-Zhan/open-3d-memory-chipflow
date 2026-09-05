# SPDX-License-Identifier: Apache-2.0
set_thread_count 6
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
read_db /output/eco_unplaced.odb
read_sdc /input/cts.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
set_propagated_clock [all_clocks]
detailed_placement
check_placement -verbose
estimate_parasitics -placement
report_metrics cts_branch_eco
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical.rpt
write_db /output/cts.odb
write_def /output/cts.def
write_verilog /output/cts.v
write_sdc /output/cts.sdc
puts {CTS_BRANCH_ECO: completed; route and complete signoff still required}
