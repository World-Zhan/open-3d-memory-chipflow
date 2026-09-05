# SPDX-License-Identifier: Apache-2.0
set_thread_count 2
source scripts/init_tech_sg13g2.tcl
read_lef /input/bondpad70_m2_ring.lef
read_def /output/pad_io_access.def
make_tracks
set master [[ord::get_db] findMaster bondpad70_m2_ring]
set pin [$master findMTerm pad]
set f [open /output/loaded_pin_geometry.tsv w]
puts $f "layer\txmin_dbu\tymin_dbu\txmax_dbu\tymax_dbu"
foreach box [$pin getGeometry] {
    puts $f "[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
}
close $f
help pin_access
pin_access -bottom_routing_layer Metal2 -top_routing_layer TopMetal2
write_db /output/pad_io_access.odb
write_def /output/pad_io_access_checked.def
puts {PAD_IO_ACCESS: pin-access-only experiment completed; no route or signoff}
