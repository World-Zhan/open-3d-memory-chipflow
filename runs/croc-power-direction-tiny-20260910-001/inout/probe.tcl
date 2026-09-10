set_thread_count 2
define_corners tt
read_liberty -corner tt /work/upstream/croc/technology/lib/sg13g2_stdcell_typ_1p20V_25C.lib
read_liberty -corner tt /work/upstream/croc/technology/lib/sg13g2_io_typ_1p2V_3p3V_25C.lib
read_lef /work/upstream/croc/technology/lef/sg13g2_tech.lef
read_lef /work/upstream/croc/technology/lef/sg13g2_stdcell.lef
read_lef /work/upstream/croc/technology/lef/sg13g2_io.lef
read_lef /output/bondpad.lef
read_def /output/input.def
read_sdc /output/input.sdc

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
report_power -instances [get_cells ff] -corner tt -digits 8 > /output/ff_power_tt.rpt
puts POWER_DIRECTION_AB_COMPLETE
