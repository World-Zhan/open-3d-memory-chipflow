# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
source /output/capture_placement.tcl
read_db /output/inputs/cts.odb
read_sdc /output/inputs/cts.sdc
setDefaultParasitics
set_propagated_clock [all_clocks]
estimate_parasitics -placement
verify_placement_ports
capture_placement before
report_metrics before_cts
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/before_electrical_violators.rpt
set block [ord::get_db_block]
set master [[ord::get_db] findMaster sg13g2_buf_4]
if {$master eq "NULL"} {error "Missing actual buffer master"}
# Freeze original standard-cell geometry only during legalization; restore each
# exact placement status in the fresh checker before final evidence capture.
set original [open /output/original_core_status.tsv w]
puts $original "instance\tstatus"
foreach inst [$block getInsts] {
    if {[[$inst getMaster] getType] eq "CORE"} {
        puts $original "[$inst getName]\t[$inst getPlacementStatus]"
        $inst setPlacementStatus FIRM
    }
}
close $original
set planned [open /output/planned_branches.tsv r]
gets $planned header
set moved [open /output/eco_loads.tsv w]
puts $moved "buffer\toriginal_net\tload_pin"
set made 0
while {[gets $planned line] >= 0} {
    lassign [split $line \t] instance pin net_name name xcenter bottom
    set inst [$block findInst $instance]
    if {$inst eq "NULL"} {error "Missing original SRAM instance"}
    set driver [$inst findITerm $pin]
    if {$driver eq "NULL" || [$driver getIoType] ne "OUTPUT"} {error "Invalid SRAM driver"}
    set net [$driver getNet]
    if {$net eq "NULL" || [$net getName] ne $net_name || [$net getSigType] ne "SIGNAL" || [$net getNonDefaultRule] ne "NULL"} {error "SRAM net metadata changed"}
    set loads {}
    foreach term [$net getITerms] {
        if {[$term getIoType] eq "INPUT"} {lappend loads $term}
    }
    if {[llength $loads] != 4 || [llength [$net getITerms]] != 5 || [llength [$net getBTerms]] != 0} {error "SRAM fanout changed"}
    if {[$block findInst $name] ne "NULL" || [$block findNet $name] ne "NULL"} {error "ECO identity collision"}
    set buf [odb::dbInst_create $block $master $name]
    $buf setLocation [expr {int($xcenter - [$master getWidth]/2)}] [expr {int($bottom - 2*[$master getHeight])}]
    $buf setPlacementStatus PLACED
    set output [odb::dbNet_create $block $name]
    $output setSigType SIGNAL
    [$buf findITerm A] connect $net
    [$buf findITerm X] connect $output
    foreach term $loads {
        set identity "[[$term getInst] getName]/[[$term getMTerm] getName]"
        $term disconnect
        $term connect $output
        puts $moved "$name\t$net_name\t$identity"
    }
    foreach pg {VDD VSS} {
        set term [$buf findITerm $pg]
        set supply [$block findNet $pg]
        if {$term eq "NULL" || $supply eq "NULL"} {error "Missing explicit buffer supply"}
        $term connect $supply
    }
    incr made
}
close $planned
close $moved
if {$made != 64} {error "Expected exactly 64 SRAM output buffers"}
write_db /output/eco_unplaced.odb
puts {SRAM_CAP_EDIT_COMPLETE}
