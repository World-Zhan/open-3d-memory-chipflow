source scripts/startup.tcl
set_thread_count 2
read_lef /output/bondpad.lef
read_def /work/runs/croc-placement-sta-readback-20260909-001/candidate/inputs/02_croc.placed.def
read_sdc /work/runs/croc-placement-sta-readback-20260909-001/candidate/inputs/02_croc.placed.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
estimate_parasitics -placement

help report_power > /output/power_command_help.rpt
help set_power_activity > /output/activity_command_help.rpt
set f [open /output/activity_command_body.tcl w]
puts $f [info body sta::set_power_activity]
close $f

set f [open /output/bondpad_directions.tsv w]
puts $f "instance\tmaster\tpin\tdirection\tnet"
set block [ord::get_db_block]
foreach inst [$block getInsts] {
    if {[[$inst getMaster] getName] eq "bondpad70_m2_ring"} {
        foreach it [$inst getITerms] {
            set mt [$it getMTerm]
            set net [$it getNet]
            set netname ""
            if {$net ne "NULL"} {set netname [$net getName]}
            puts $f "[$inst getName]\tbondpad70_m2_ring\t[$mt getName]\t[$mt getIoType]\t$netname"
        }
    }
}
close $f
write_def /output/readback.def
write_sdc /output/readback.sdc
write_verilog /output/readback.v
report_clock_properties > /output/clocks.rpt
report_power -corner tt -digits 8 > /output/power_tt.rpt
report_activity_annotation -report_annotated > /output/activity_annotation.rpt
set srams [get_cells -quiet -filter {ref_name == RM_IHPSG13_1P_512x32_c2_bm_bist} *]
report_power -instances $srams -corner tt -digits 8 > /output/sram_power_tt.rpt
report_power -corner ff -digits 8 > /output/power_ff.rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical_violators.rpt
puts POWER_DIRECTION_AB_COMPLETE
