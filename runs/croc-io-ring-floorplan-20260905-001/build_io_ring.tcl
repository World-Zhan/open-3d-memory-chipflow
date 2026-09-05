# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
source scripts/init_tech_sg13g2.tcl
read_lef /reference/bondpad70_m2_ring.lef
read_def /output/io_ring_input.def
set chipW 1974
set chipH 1974
set padD 180
set padW 80
# IO offset is an integer multiple of the 1um IO site width.
set padBond 92
set bondPadCell bondpad70_m2_ring
source /output/padring_candidate.tcl
foreach {net pin kind} {VDD vdd power VSS vss ground VDDIO iovdd power VSSIO iovss ground} {
    add_global_connection -net $net -inst_pattern {.*} -pin_pattern $pin -$kind
}
global_connect
make_tracks
set f [open /output/instances.tsv w]
puts $f "name\tmaster\torientation\txmin\tymin\txmax\tymax"
set t [open /output/terminals.tsv w]
puts $t "instance\tpin\tnet"
foreach inst [[ord::get_db_block] getInsts] {
    set box [$inst getBBox]
    puts $f "[$inst getName]\t[[$inst getMaster] getName]\t[$inst getOrient]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
    foreach iterm [$inst getITerms] {
        set net [$iterm getNet]
        set name {UNCONNECTED}
        if {$net != "NULL"} {set name [$net getName]}
        puts $t "[$inst getName]\t[[$iterm getMTerm] getName]\t$name"
    }
}
close $f
close $t
write_def /output/io_ring.def
write_db /output/io_ring.odb
puts {IO_RING_FLOORPLAN_COMPLETE: IO-only placement; no core, route, extraction or signoff}
