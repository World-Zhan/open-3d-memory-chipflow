set_thread_count 2
define_corners tt ff ss
read_liberty -corner tt /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lib/sg13g2_io_typ_1p2V_3p3V_25C.lib
read_liberty -corner ff /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lib/sg13g2_io_fast_1p32V_3p6V_m40C.lib
read_liberty -corner ss /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lib/sg13g2_io_slow_1p08V_3p0V_125C.lib
read_lef /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef
read_lef /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.ref/sg13g2_io/lef/sg13g2_io.lef
read_def /output/input.def
read_sdc /output/input.sdc
help report_check_types > /output/tt/check_help.rpt
report_check_types -corner tt -max_slew -max_capacitance -max_fanout -digits 8 > /output/tt/electrical_all.rpt
report_check_types -corner tt -max_slew -max_capacitance -max_fanout -violators -digits 8 > /output/tt/electrical_violators.rpt
report_checks -corner tt -from [get_ports out_core] -to [get_ports out_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/tt/out16_path.rpt
report_checks -corner tt -from [get_ports bi_tx_core] -to [get_ports bi_tx_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/tt/bidir_tx_path.rpt
report_checks -corner tt -from [get_ports bi_rx_pad] -to [get_ports bi_rx_rx] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/tt/bidir_rx_path.rpt
report_checks -corner tt -from [get_ports in_pad] -to [get_ports in_core] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/tt/input_path.rpt
report_checks -corner tt -from [get_ports bi_z_core] -to [get_ports bi_z_pad] -unconstrained -path_delay min_max -fields {slew cap fanout} -digits 8 > /output/tt/bidir_highz_path.rpt
report_clock_properties > /output/tt/clocks.rpt
# Mode evidence is preserved by write_sdc below; report_case_analysis is absent in this fixed binary.
check_setup -verbose > /output/tt/constraints.rpt
report_power -corner tt -digits 8 > /output/tt/raw_default_power.rpt
write_sdc /output/tt/readback.sdc
write_def /output/tt/readback.def
set f [open /output/tt/actual_terms.tsv w]
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
puts IHP_IO_SUITE_CORNER_COMPLETE_tt

help report_check_types > /output/ff/check_help.rpt
report_check_types -corner ff -max_slew -max_capacitance -max_fanout -digits 8 > /output/ff/electrical_all.rpt
report_check_types -corner ff -max_slew -max_capacitance -max_fanout -violators -digits 8 > /output/ff/electrical_violators.rpt
report_checks -corner ff -from [get_ports out_core] -to [get_ports out_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ff/out16_path.rpt
report_checks -corner ff -from [get_ports bi_tx_core] -to [get_ports bi_tx_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ff/bidir_tx_path.rpt
report_checks -corner ff -from [get_ports bi_rx_pad] -to [get_ports bi_rx_rx] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ff/bidir_rx_path.rpt
report_checks -corner ff -from [get_ports in_pad] -to [get_ports in_core] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ff/input_path.rpt
report_checks -corner ff -from [get_ports bi_z_core] -to [get_ports bi_z_pad] -unconstrained -path_delay min_max -fields {slew cap fanout} -digits 8 > /output/ff/bidir_highz_path.rpt
report_clock_properties > /output/ff/clocks.rpt
# Mode evidence is preserved by write_sdc below; report_case_analysis is absent in this fixed binary.
check_setup -verbose > /output/ff/constraints.rpt
report_power -corner ff -digits 8 > /output/ff/raw_default_power.rpt
write_sdc /output/ff/readback.sdc
write_def /output/ff/readback.def
set f [open /output/ff/actual_terms.tsv w]
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
puts IHP_IO_SUITE_CORNER_COMPLETE_ff

help report_check_types > /output/ss/check_help.rpt
report_check_types -corner ss -max_slew -max_capacitance -max_fanout -digits 8 > /output/ss/electrical_all.rpt
report_check_types -corner ss -max_slew -max_capacitance -max_fanout -violators -digits 8 > /output/ss/electrical_violators.rpt
report_checks -corner ss -from [get_ports out_core] -to [get_ports out_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ss/out16_path.rpt
report_checks -corner ss -from [get_ports bi_tx_core] -to [get_ports bi_tx_pad] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ss/bidir_tx_path.rpt
report_checks -corner ss -from [get_ports bi_rx_pad] -to [get_ports bi_rx_rx] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ss/bidir_rx_path.rpt
report_checks -corner ss -from [get_ports in_pad] -to [get_ports in_core] -path_delay min_max -format full_clock_expanded -fields {slew cap fanout} -digits 8 > /output/ss/input_path.rpt
report_checks -corner ss -from [get_ports bi_z_core] -to [get_ports bi_z_pad] -unconstrained -path_delay min_max -fields {slew cap fanout} -digits 8 > /output/ss/bidir_highz_path.rpt
report_clock_properties > /output/ss/clocks.rpt
# Mode evidence is preserved by write_sdc below; report_case_analysis is absent in this fixed binary.
check_setup -verbose > /output/ss/constraints.rpt
report_power -corner ss -digits 8 > /output/ss/raw_default_power.rpt
write_sdc /output/ss/readback.sdc
write_def /output/ss/readback.def
set f [open /output/ss/actual_terms.tsv w]
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
puts IHP_IO_SUITE_CORNER_COMPLETE_ss

set f [open /output/combined_counts.tsv w]
puts $f "check	count	scope"
puts $f "max_slew	[sta::max_slew_violation_count]	aggregate_tt_ff_ss"
puts $f "max_capacitance	[sta::max_capacitance_violation_count]	aggregate_tt_ff_ss"
puts $f "max_fanout	[sta::max_fanout_violation_count]	aggregate_tt_ff_ss"
puts $f "setup	[sta::endpoint_violation_count max]	tiny_paths_only"
puts $f "hold	[sta::endpoint_violation_count min]	tiny_paths_only"
close $f
puts IHP_IO_SUITE_STA_COMPLETE
