
source scripts/startup.tcl
set_thread_count 2
read_db /output/inputs/02_croc.placed.odb
read_sdc /output/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement
check_placement -verbose
check_setup -verbose > /output/constraints.rpt
help report_power > /output/power_command_help.rpt
report_metrics fresh_placed
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical_violators.rpt
report_checks -path_delay min -slack_max 0 -format full_clock_expanded -fields {slew cap fanout} > /output/hold_violators.rpt
write_sdc /output/readback.sdc
set f [open /output/core_pg.tsv w]
puts $f "net\ttcl_catch_code\tmessage"
foreach net {VDD VSS} {
    puts "FRESH_PLACED_PG_BEGIN $net"
    set code [catch {check_power_grid -net $net -error_file /output/pg_errors_${net}.rpt} message]
    puts $f "$net\t$code\t[string map [list \n { } \t { }] $message]"
    puts "FRESH_PLACED_PG_END $net catch=$code result=$message"
}
close $f
puts {FRESH_PLACED_READBACK_COMPLETE}
