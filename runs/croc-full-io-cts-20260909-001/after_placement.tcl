
# Bind PG on cells added by the original repair operations.
global_connect
verify_placement_ports
capture_placement after
set f [open /output/placement_checks.tsv w]
puts $f "check\ttcl_catch_code\tmessage"
puts {PLACEMENT_LEGALITY_BEGIN}
set code [catch {check_placement -verbose} message]
puts $f "check_placement\t$code\t[string map [list \n { } \t { }] $message]"
puts "PLACEMENT_LEGALITY_END catch=$code result=$message"
foreach net {VDD VSS} {
    puts "PLACED_PG_CHECK_BEGIN $net"
    set code [catch {check_power_grid -net $net -error_file /output/pg_errors_${net}.rpt} message]
    puts $f "check_power_grid_$net\t$code\t[string map [list \n { } \t { }] $message]"
    puts "PLACED_PG_CHECK_END $net catch=$code result=$message"
}
close $f
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical_violators.rpt
puts {FULL_PLACEMENT_EVIDENCE_CAPTURE_COMPLETE}
