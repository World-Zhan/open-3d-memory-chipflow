
source scripts/startup.tcl
set_thread_count 2
read_db /source/inputs/02_croc.placed.odb
set af [open /output/api_inventory.txt w]
foreach pattern {sta::*activity* sta::*power* sta::*debug* utl::*debug* sta::*clock*} {
    puts $af "$pattern [lsort [info commands $pattern]]"
}
foreach proc {sta::report_power sta::report_activity_annotation sta::set_debug_level utl::set_debug_level} {
    if {[llength [info procs $proc]]} {puts $af "$proc\n[info body $proc]"}
}
close $af
set mf [open /output/bondpad_master_directions.tsv w]
puts $mf "master\tpin\tio_type\tsignal_type"
foreach lib [[ord::get_db] getLibs] {
    foreach name {bondpad_70x70 bondpad70_m2_ring} {
        set master [$lib findMaster $name]
        if {$master != "NULL"} {
            foreach mt [$master getMTerms] {
                puts $mf "$name\t[$mt getName]\t[$mt getIoType]\t[$mt getSigType]"
            }
        }
    }
}
close $mf
set cf [open /output/direction_change.tsv w]
puts $cf "master\tpin\tbefore\tafter"
foreach lib [[ord::get_db] getLibs] {
    set master [$lib findMaster bondpad70_m2_ring]
    if {$master != "NULL"} {
        set mt [$master findMTerm pad]
        set before [$mt getIoType]
        if {$before != "INOUT"} {error "Expected original INOUT pad"}
        $mt setIoType INPUT
        puts $cf "bondpad70_m2_ring\tpad\t$before\t[$mt getIoType]"
    }
}
close $cf
read_sdc /source/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement
report_clock_properties > /output/clocks.rpt
report_power -corner tt -digits 8 > /output/power_tt.rpt
report_power -corner ff -digits 8 > /output/power_ff.rpt
set srams [get_cells -quiet -filter {ref_name == RM_IHPSG13_1P_512x32_c2_bm_bist} *]
report_power -instances $srams -corner tt -digits 8 > /output/sram_power_tt.rpt
if {[llength [info commands sta::report_activity_annotation]]} {
    catch {report_activity_annotation > /output/activity_annotation.rpt} activity_message
}
write_sdc /output/readback.sdc
puts POWER_DIRECTION_PROBE_COMPLETE
