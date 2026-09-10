# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
source /output/capture_placement.tcl
read_db /output/eco_unplaced.odb
read_sdc /output/inputs/cts.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
set_propagated_clock [all_clocks]
detailed_placement
set original [open /output/original_core_status.tsv r]
gets $original header
set block [ord::get_db_block]
while {[gets $original line] >= 0} {
    lassign [split $line 	] name status
    set inst [$block findInst $name]
    if {$inst eq "NULL"} {error "Original CORE disappeared"}
    $inst setPlacementStatus $status
}
close $original
estimate_parasitics -placement
source /output/after_placement.tcl
report_metrics after_cts
write_db /output/cts.odb
puts {FULL_SRAM_CAP_ECO_COMPLETE}
