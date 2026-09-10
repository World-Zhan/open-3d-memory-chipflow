###############################################################################
# Created by write_sdc
# Thu Sep 10 14:40:59 2026
###############################################################################
current_design ihp_io_suite_tiny
###############################################################################
# Timing Constraints
###############################################################################
create_clock -name clk_sys -period 10.0000 [get_ports {clk_pad}]
set_clock_transition 0.2000 [get_clocks {clk_sys}]
set_clock_uncertainty 0.1000 clk_sys
set_input_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {bi_rx_pad}]
set_input_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {bi_rx_pad}]
set_input_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {bi_tx_core}]
set_input_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {bi_tx_core}]
set_input_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {in_pad}]
set_input_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {in_pad}]
set_input_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {out_core}]
set_input_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {out_core}]
set_output_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {bi_rx_rx}]
set_output_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {bi_rx_rx}]
set_output_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {bi_tx_pad}]
set_output_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {bi_tx_pad}]
set_output_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {in_core}]
set_output_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {in_core}]
set_output_delay 1.0000 -clock [get_clocks {clk_sys}] -min -add_delay [get_ports {out_pad}]
set_output_delay 3.0000 -clock [get_clocks {clk_sys}] -max -add_delay [get_ports {out_pad}]
###############################################################################
# Environment
###############################################################################
set_load -pin_load 15.0000 [get_ports {out_pad}]
set_load -pin_load 15.0000 [get_ports {bi_tx_pad}]
set_load -pin_load 0.0500 [get_ports {bi_tx_rx}]
set_load -pin_load 15.0000 [get_ports {bi_rx_pad}]
set_load -pin_load 0.0500 [get_ports {bi_rx_rx}]
set_load -pin_load 15.0000 [get_ports {bi_z_pad}]
set_load -pin_load 0.0500 [get_ports {bi_z_rx}]
set_load -pin_load 0.0500 [get_ports {in_core}]
set_load -pin_load 0.0500 [get_ports {clk_core}]
set_driving_cell -lib_cell sg13g2_IOPadOut16mA -pin {pad} -input_transition_rise 0.0000 -input_transition_fall 0.0000 [get_ports {bi_rx_pad}]
set_driving_cell -lib_cell sg13g2_IOPadOut16mA -pin {pad} -input_transition_rise 0.0000 -input_transition_fall 0.0000 [get_ports {in_pad}]
set_input_transition 0.2000 [get_ports {out_core}]
set_input_transition 0.2000 [get_ports {bi_tx_core}]
set_input_transition 0.2000 [get_ports {bi_tx_en}]
set_input_transition 0.2000 [get_ports {bi_rx_core}]
set_input_transition 0.2000 [get_ports {bi_rx_en}]
set_input_transition 0.2000 [get_ports {bi_z_core}]
set_input_transition 0.2000 [get_ports {bi_z_en}]
set_case_analysis 0 [get_ports {bi_rx_en}]
set_case_analysis 1 [get_ports {bi_tx_en}]
set_case_analysis 0 [get_ports {bi_z_en}]
###############################################################################
# Design Rules
###############################################################################
set_max_transition 1.2000 [current_design]
