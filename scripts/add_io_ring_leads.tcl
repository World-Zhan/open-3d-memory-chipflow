# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
read_db /input/io_ring.odb
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
    set net [[$bond findITerm pad] getNet]
    if {$net == "NULL"} {error "Unconnected bondpad $name"}
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
    incr count
}
close $f
if {$count != 64} {error "Expected exactly 64 bondpad leads, found $count"}
write_db /output/io_ring.odb
write_def /output/io_ring.def
puts {IO_RING_LEADS_COMPLETE: 64 leads across six metal layers; core routing absent}
