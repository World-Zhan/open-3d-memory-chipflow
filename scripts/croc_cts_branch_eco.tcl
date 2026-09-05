# SPDX-License-Identifier: Apache-2.0
# Evidence-specific repair: the four measured 16-load clock branches become
# two groups of eight through matched non-inverting buffers. No rule relaxation.
set_thread_count 6
set report_dir /output
source scripts/init_tech_sg13g2.tcl
source scripts/reports.tcl
read_db /input/cts.odb
read_sdc /input/cts.sdc
setDefaultParasitics
set_dont_use $dont_use_cells
set_propagated_clock [all_clocks]
if {![llength [info commands insert_buffer]]} {error "Pinned tool lacks insert_buffer"}
help insert_buffer
set block [ord::get_db_block]
foreach branch {0 1 2 3} {
    set inst [$block findInst clkbuf_2_${branch}_0_soc_clk_i_regs]
    if {$inst eq "NULL"} {error "Expected branch instance missing"}
    set driver [$inst findITerm X]
    set net [$driver getNet]
    set loads {}
    foreach iterm [$net getITerms] {
        if {[$iterm getIoType] eq "INPUT"} {
            lappend loads "[[$iterm getInst] getName]/[[$iterm getMTerm] getName]"
        }
    }
    set loads [lsort $loads]
    if {[llength $loads] != 16} {error "Branch no longer has the diagnosed 16 loads"}
    foreach group {0 1} {
        set selected [lrange $loads [expr {$group*8}] [expr {$group*8+7}]]
        puts "ECO_GROUP branch=$branch group=$group loads=$selected"
        insert_buffer -buffer_cell sg13g2_buf_8 -load_pins $selected \
            -buffer_name eco_cts_b${branch}_g${group} -net_name eco_cts_b${branch}_g${group}
    }
}
detailed_placement
check_placement -verbose
estimate_parasitics -placement
report_metrics cts_branch_eco
report_check_types -max_slew -max_capacitance -max_fanout -violators > /output/electrical.rpt
write_db /output/cts.odb
write_def /output/cts.def
write_verilog /output/cts.v
write_sdc /output/cts.sdc
puts {CTS_BRANCH_ECO: completed; route, equivalence and signoff not yet validated}
