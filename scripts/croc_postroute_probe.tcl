# SPDX-License-Identifier: Apache-2.0
# Read-only layout experiment. Do not write ODB/DEF after RCX: extraction may
# alter in-memory routing patches in this pinned OpenROAD version.
set_thread_count 6
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
read_db $::env(CROC_ODB)
read_sdc $::env(CROC_SDC)
setDefaultParasitics
set_propagated_clock [all_clocks]
puts {PROBE: diagnose with placement-estimated parasitics before RCX}
estimate_parasitics -placement
report_metrics probe_placement_estimated
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/placement_electrical.rpt
check_setup -verbose > /output/constraints_check.rpt
puts {PROBE: extract typical RC model from immutable routed database}
define_process_corner -ext_model_index 0 X
extract_parasitics -ext_model_file $::env(CROC_RCX_RULES)
write_spef /output/croc.typ.spef
read_spef -corner tt /output/croc.typ.spef
read_spef -corner ff /output/croc.typ.spef
report_metrics probe_extracted_typ_rc
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/extracted_electrical.rpt
report_checks -corner tt -path_delay min_max -group_path_count 10 -fields {slew cap input nets fanout} > /output/tt_paths.rpt
report_checks -corner ff -path_delay min_max -group_path_count 10 -fields {slew cap input nets fanout} > /output/ff_paths.rpt
report_power -corner tt > /output/tt_power.rpt
report_power -corner ff > /output/ff_power.rpt
puts {PROBE: completed; no layout repair or signoff promotion}
