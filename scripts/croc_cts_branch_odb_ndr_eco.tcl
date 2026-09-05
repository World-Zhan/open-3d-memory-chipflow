# SPDX-License-Identifier: Apache-2.0
# Compatibility path for the pinned tool without insert_buffer. OpenDB edits
# are written to a new ODB and STA is performed in a fresh OpenROAD process.
set_thread_count 6
source scripts/init_tech_sg13g2.tcl
read_db /input/cts.odb
set block [ord::get_db_block]
set master [[ord::get_db] findMaster sg13g2_buf_8]
if {$master eq "NULL"} {error "Buffer master missing"}
set groups [open /output/eco_groups.tsv w]
puts $groups "parent\tbuffer\tload_pin"
foreach branch {0 1 2 3} {
    set parent_name clkbuf_2_${branch}_0_soc_clk_i_regs
    set inst [$block findInst $parent_name]
    if {$inst eq "NULL"} {error "Expected branch instance missing"}
    set net [[$inst findITerm X] getNet]
    set loads {}
    foreach iterm [$net getITerms] {
        if {[$iterm getIoType] eq "INPUT"} {
            lappend loads [list "[[$iterm getInst] getName]/[[$iterm getMTerm] getName]" $iterm]
        }
    }
    set loads [lsort -index 0 $loads]
    if {[llength $loads] != 16} {error "Branch no longer has exactly 16 diagnosed loads"}
    lassign [$inst getLocation] x y
    foreach group {0 1} {
        set name eco_cts_b${branch}_g${group}
        if {[$block findInst $name] ne "NULL" || [$block findNet $name] ne "NULL"} {error "ECO name collision"}
        set buf [odb::dbInst_create $block $master $name]
        $buf setLocation $x $y
        $buf setPlacementStatus PLACED
        set new_net [odb::dbNet_create $block $name]
        $new_net setSigType CLOCK
        set inherited_ndr [$net getNonDefaultRule]
        if {$inherited_ndr eq "NULL"} {error "Expected parent clock NDR is absent"}
        $new_net setNonDefaultRule $inherited_ndr
        puts "ECO_NDR $name inherits [$inherited_ndr getName]"
        [$buf findITerm A] connect $net
        [$buf findITerm X] connect $new_net
        foreach item [lrange $loads [expr {$group*8}] [expr {$group*8+7}]] {
            lassign $item pin_name pin
            $pin disconnect
            $pin connect $new_net
            puts $groups "$parent_name\t$name\t$pin_name"
        }
        foreach pg {VDD VSS} {
            set pin [$buf findITerm $pg]
            set supply [$block findNet $pg]
            if {$pin eq "NULL" || $supply eq "NULL"} {error "Missing explicit buffer supply"}
            $pin connect $supply
        }
    }
}
close $groups
write_db /output/eco_unplaced.odb
puts {CTS_ECO_EDIT: wrote isolated ODB; restart before timing analysis}
