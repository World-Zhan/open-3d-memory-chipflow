set_thread_count 2
define_corners tt
read_liberty -corner tt /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lib/sg13g2_io_typ_1p2V_3p3V_25C.lib
read_lef /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef
read_lef /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lef/sg13g2_io.lef
read_def /output/input.def
read_sdc /output/input.sdc
help report_check_types > /output/check_help.rpt
report_check_types -max_slew -max_capacitance -max_fanout -digits 8 > /output/electrical_all.rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators -digits 8 > /output/electrical_violators.rpt
report_checks -from [get_ports out_core] -to [get_ports out_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/out16_path.rpt
report_checks -from [get_ports bi_tx_core] -to [get_ports bi_tx_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/bidir_tx_path.rpt
report_checks -from [get_ports bi_rx_pad] -to [get_ports bi_rx_rx] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/bidir_rx_path.rpt
report_checks -from [get_ports in_pad] -to [get_ports in_core] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/input_path.rpt
report_checks -from [get_ports bi_z_core] -to [get_ports bi_z_pad] -unconstrained -path_delay min_max -fields {slew cap fanout} -digits 8 > /output/bidir_highz_path.rpt
report_clock_properties > /output/clocks.rpt
report_case_analysis > /output/case_analysis.rpt
check_setup -verbose > /output/constraints.rpt
report_power -corner tt -digits 8 > /output/raw_default_power.rpt
write_sdc /output/readback.sdc
write_def /output/readback.def
set f [open /output/actual_terms.tsv w]
puts $f "instance	master	pin	direction	signal_type	net"
foreach inst [[ord::get_db_block] getInsts] {
    foreach it [$inst getITerms] {
        set mt [$it getMTerm]
        set net [$it getNet]
        set netname ""
        if {$net ne "NULL"} {set netname [$net getName]}
        puts $f "[$inst getName]	[[$inst getMaster] getName]	[$mt getName]	[$mt getIoType]	[$mt getSigType]	$netname"
    }
}
close $f
puts IHP_IO_SUITE_STA_COMPLETE
