
set_thread_count 2
read_db /output/inputs/01_croc.floorplan.odb
help check_power_grid
set block [ord::get_db_block]
set f [open /output/top_pin_boxes.tsv w]
puts $f "port\tnet\tio_type\tsignal_type\tlayer\txmin\tymin\txmax\tymax\tplacement_status"
foreach port [$block getBTerms] {
    foreach pin [$port getBPins] {
        foreach box [$pin getBoxes] {
            puts $f "[$port getName]\t[[$port getNet] getName]\t[$port getIoType]\t[$port getSigType]\t[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]\t[$pin getPlacementStatus]"
        }
    }
}
close $f
set f [open /output/bondpad_boxes.tsv w]
puts $f "instance\tnet\txmin\tymin\txmax\tymax"
foreach inst [$block getInsts] {
    if {[[$inst getMaster] getName] != "bondpad70_m2_ring"} {continue}
    set box [$inst getBBox]
    set net [[ $inst findITerm pad ] getNet]
    if {$net == "NULL"} {error "Unconnected actual bondpad"}
    puts $f "[$inst getName]\t[$net getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
}
close $f
set f [open /output/pg_checks.tsv w]
puts $f "net\ttcl_catch_code\tmessage"
foreach net {VDD VSS} {
    puts "STATIC_PG_CHECK_BEGIN $net"
    set code [catch {check_power_grid -net $net -floorplanning -error_file /output/pg_errors_${net}.rpt} message]
    puts $f "$net\t$code\t[string map [list \n { } \t { }] $message]"
    puts "STATIC_PG_CHECK_END $net catch=$code"
}
close $f
puts {FULL_FLOORPLAN_READBACK_COMPLETE}
