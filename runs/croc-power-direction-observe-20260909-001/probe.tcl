
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

close $cf
read_sdc /source/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement
report_clock_properties > /output/clocks.rpt
report_power -corner tt -digits 8 > /output/power_tt.rpt
report_power -corner ff -digits 8 > /output/power_ff.rpt
set obs [open /output/pin_observations.tsv w]
puts $obs "object\tproperty\tcode\tvalue"
set pins [get_pins -quiet {pad_clk_i/pad pad_clk_i/p2c pad_ref_clk_i/pad pad_ref_clk_i/p2c pad_jtag_tck_i/pad pad_jtag_tck_i/p2c IO_BOND_pad_clk_i/pad IO_BOND_pad_ref_clk_i/pad IO_BOND_pad_jtag_tck_i/pad}]
set srams [get_cells -quiet -filter {ref_name == RM_IHPSG13_1P_512x32_c2_bm_bist} *]
foreach sram $srams {
    set name [get_full_name $sram]
    foreach pin [get_pins -of_objects $sram] {
        if {[string match */A_CLK [get_full_name $pin]]} {lappend pins $pin}
    }
}
foreach pin $pins {
    set name [get_full_name $pin]
    foreach prop {direction is_clock is_ideal_clock capacitance rise_slew fall_slew activity} {
        set code [catch {get_property $pin $prop} val]
        puts $obs "$name\t$prop\t$code\t[string map [list \n { } \t { }] $val]"
    }
    set code [catch {get_clocks -of_objects $pin} clocks]
    set names {}
    if {!$code} {foreach clk $clocks {lappend names [get_full_name $clk]}}
    puts $obs "$name\tclock_names\t$code\t$names"
}
close $obs
report_power -instances $srams -corner tt -digits 8 > /output/sram_power_tt.rpt
if {[llength [info commands sta::report_activity_annotation]]} {
    catch {report_activity_annotation > /output/activity_annotation.rpt} activity_message
}
# Debug availability is runtime-observed before use; retain exact power procedure body.
if {[llength [info commands utl::set_debug_level]]} {
    set debugcode [catch {
        utl::set_debug_level STA power 2
        report_power -instances $srams -corner tt -digits 8 > /output/sram_debug.rpt
        utl::set_debug_level STA power 0
    } debugmessage]
    set df [open /output/debug_status.tsv w]
    puts $df "$debugcode\t$debugmessage"
    close $df
}
write_sdc /output/readback.sdc
puts POWER_DIRECTION_PROBE_COMPLETE
