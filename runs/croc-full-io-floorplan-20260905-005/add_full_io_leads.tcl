# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
set block [ord::get_db_block]
set tech [[ord::get_db] getTech]
set f [open /output/lead_boxes.tsv w]
puts $f "bond\tio\tnet\tlayer\txmin\tymin\txmax\tymax"
set count 0
foreach bond [$block getInsts] {
    set name [$bond getName]
    if {![string match IO_BOND_pad_* $name]} {continue}
    set io [$block findInst [string range $name 8 end]]
    if {$io == "NULL"} {error "Missing actual IO for $name"}
    set b [$bond getBBox]
    set a [$io getBBox]
    switch -- [$io getOrient] {
        R0 {set coords [list [$b xMin] [$b yMax] [$b xMax] [$a yMin]]}
        MX {set coords [list [$b xMin] [$a yMax] [$b xMax] [$b yMin]]}
        MXR90 {set coords [list [$b xMax] [$b yMin] [$a xMin] [$b yMax]]}
        R90 {set coords [list [$a xMax] [$b yMin] [$b xMin] [$b yMax]]}
        default {error "Unexpected IO orientation for $name"}
    }
    lassign $coords x1 y1 x2 y2
    set w [expr {$x2-$x1}]
    set h [expr {$y2-$y1}]
    if {![expr {($w==4200 && $h==70000)||($w==70000 && $h==4200)}]} {error "Unexpected lead bbox $coords"}
    # A separated cover macro is not connected automatically by place_bondpad.
    # Bind it to the actual IO external pad/supply terminal, never an implicit net.
    set io_master [[$io getMaster] getName]
    set pin pad
    switch -- $io_master {
        sg13g2_IOPadVdd {set pin vdd}
        sg13g2_IOPadVss {set pin vss}
        sg13g2_IOPadIOVdd {set pin iovdd}
        sg13g2_IOPadIOVss {set pin iovss}
    }
    set terminal [$io findITerm $pin]
    if {$terminal == "NULL"} {error "Missing external terminal $pin on $io_master"}
    set net [$terminal getNet]
    if {$net == "NULL"} {error "Unconnected source IO terminal on $name"}
    set target [$bond findITerm pad]
    if {[$target getNet] != "NULL" && [$target getNet] != $net} {error "Conflicting bondpad net on $name"}
    $target connect $net
    set shared 0
    foreach term [$io getITerms] {if {[$term getNet] == $net} {set shared 1}}
    if {!$shared} {error "Bondpad and IO have no shared net"}
    $net setSpecial
    set wire [odb::dbSWire_create $net ROUTED]
    foreach layer {Metal2 Metal3 Metal4 Metal5 TopMetal1 TopMetal2} {
        set box [odb::dbSBox_create $wire [$tech findLayer $layer] $x1 $y1 $x2 $y2 IOWIRE]
        if {$box == "NULL"} {error "Failed to create $name $layer lead"}
        puts $f "$name\t[$io getName]\t[$net getName]\t$layer\t$x1\t$y1\t$x2\t$y2"
    }
# Bind each real external net to one physical TopMetal2 terminal on its bondpad.
set topterms [$net getBTerms]
if {[llength $topterms] != 1} {error "Expected exactly one top port for bondpad $name"}
set topterm [lindex $topterms 0]
set bpin [odb::dbBPin_create $topterm]
$bpin setPlacementStatus FIRM
set pinbox [odb::dbBox_create $bpin [$tech findLayer TopMetal2] [$b xMin] [$b yMin] [$b xMax] [$b yMax]]
if {$pinbox == "NULL"} {error "Physical terminal creation failed: $name"}
    incr count
}
close $f
if {$count != 64} {error "Expected exactly 64 bondpad leads, found $count"}
puts {FULL_IO_LEADS_COMPLETE: 64 leads across six layers; full core floorplan present, signal placement/routing not run}
