# SPDX-License-Identifier: Apache-2.0
# Single-factor CTS experiment from the same immutable placed checkpoint.
set_thread_count 6
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
read_db /input/02_croc.placed.odb
read_sdc /input/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
set clock_nets [get_nets -of_objects [get_pins -of_objects "*_reg" -filter "name == CLK"]]
unset_dont_touch $clock_nets
repair_clock_inverters
set cts_args [list -buf_list $ctsBuf -root_buf $ctsBufRoot -sink_clustering_enable -repair_clock_nets]
if {$::env(CROC_CTS_CLUSTER_SIZE) ne "default"} {
    lappend cts_args -sink_clustering_size $::env(CROC_CTS_CLUSTER_SIZE)
}
clock_tree_synthesis {*}$cts_args
detailed_placement
estimate_parasitics -placement
set_propagated_clock [all_clocks]
repair_timing -setup -verbose
detailed_placement
check_placement -verbose
estimate_parasitics -placement
report_cts -out_file /output/cts.rpt
report_metrics cts_final
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical.rpt
write_db /output/cts.odb
write_def /output/cts.def
write_verilog /output/cts.v
write_sdc /output/cts.sdc
puts {CTS_AB: completed; new routing and signoff still required}
