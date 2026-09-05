# Copyright 2023 ETH Zurich and University of Bologna.
# Solderpad Hardware License, Version 0.51, see LICENSE for details.
# SPDX-License-Identifier: SHL-0.51

# Authors:
# - Tobias Senti      <tsenti@ethz.ch>
# - Jannis Schönleber <janniss@iis.ee.ethz.ch>
# - Philippe Sauter   <phsauter@iis.ee.ethz.ch>

# Stage 01: Initialization, Floorplan, and Power Grid
#
# This stage performs:
# - Reading and linking the netlist
# - Reading timing constraints
# - Connecting global power nets
# - Creating the floorplan (die/core area, macro placement, IO placement)
# - Generating the power distribution network
#
# Required environment variables:
#   PROJ_NAME    - Project name (e.g., "croc")
#   NETLIST      - Path to synthesized netlist
#   TOP_DESIGN   - Top module name
#
# Output checkpoint: 01_${PROJ_NAME}.floorplan

###############################################################################
# Setup
###############################################################################
source scripts/startup.tcl
set_thread_count 2
read_lef /reference/bondpad70_m2_ring.lef
set bondPadCell bondpad70_m2_ring

utl::report "###############################################################################"
utl::report "# Stage 01: FLOORPLAN"
utl::report "###############################################################################"

utl::report "###############################################################################"
utl::report "# 01-01: Initialization"
utl::report "###############################################################################"

# Read and check design
utl::report "Read netlist: ${netlist}"
read_verilog $netlist
link_design $top_design

utl::report "Read constraints"
read_sdc src/constraints.sdc

utl::report "Check constraints"
check_setup -verbose                                      > ${report_dir}/01-01_${proj_name}_checks.rpt
report_checks -unconstrained -format end -no_line_splits >> ${report_dir}/01-01_${proj_name}_checks.rpt
report_checks -format end -no_line_splits                >> ${report_dir}/01-01_${proj_name}_checks.rpt
report_checks -format end -no_line_splits                >> ${report_dir}/01-01_${proj_name}_checks.rpt
utl::report "Connect global nets (power)"
source scripts/power_connect.tcl

set pg_file [open /output/pg_port_binding.tsv w]
puts $pg_file "port\tbefore_type\tafter_type"
foreach {name kind} {VDD POWER VSS GROUND VDDIO POWER VSSIO GROUND} {
    set port [[ord::get_db_block] findBTerm $name]
    if {$port == "NULL" || [[$port getNet] getName] != $name || [$port getIoType] != "INOUT"} {error "Invalid supply port binding: $name"}
    set before [$port getSigType]
    if {$before != "SIGNAL" && $before != $kind} {error "Unexpected supply port type: $name $before"}
    $port setSigType $kind
    puts $pg_file "$name\t$before\t$kind"
}
close $pg_file
# Snapshot functional connectivity before any new physical cells are added.
set initial_masters [dict create]
set initial_signal_pins [dict create]
set initial_ports [dict create]
set block [ord::get_db_block]
foreach inst [$block getInsts] {
    dict set initial_masters [$inst getName] [[$inst getMaster] getName]
    foreach term [$inst getITerms] {
        set mt [$term getMTerm]
        if {[$mt getSigType] in {POWER GROUND}} {continue}
        set net [$term getNet]
        set net_name {UNCONNECTED}
        if {$net != "NULL"} {set net_name [$net getName]}
        dict set initial_signal_pins [list [$inst getName] [$mt getName]] $net_name
    }
}
foreach port [$block getBTerms] {
    dict set initial_ports [$port getName] [list [[$port getNet] getName] [$port getIoType] [$port getSigType]]
}



utl::report "###############################################################################"
utl::report "# 01-02: Core and Die Area"
utl::report "###############################################################################"
# Dimensions:                          [um]
#   final chip size (4sqmm) 2000.0 x 2000.0
#   seal ring thickness       42.0 ,   42.0 x2
#   bonding pad               70.0 ,   70.0 x2
#   io cell depth            180.0 ,  180.0 x2
#   ---------------------------------------
#   -> OR die area          1916.0 x 1916.0
#   -> OR core area         1416.0 x 1416.0
# The sealring is added after OpenROAD
# hence the OR die area is the final chip size minus the sealring thickness on each side

set chipH    1974; # OR die height (top to bottom)
set chipW    1974; # OR die width (left to right)
set padD      180; # pad depth (edge to core)
set padW       80; # pad width (beachfront)
set padBond    92; # bonding pad size
set powerRing  80; # reserved space for power ring

# starting from the outside and working towards the core area on each side
set coreMargin [expr {$padD + $padBond + $powerRing}];

utl::report "Initialize Chip"
# coordinates are lower-left x and y, upper-right x and y
initialize_floorplan -die_area "0 0 $chipW $chipH" \
                     -core_area "$coreMargin $coreMargin [expr $chipW-$coreMargin] [expr $chipH-$coreMargin]" \
                     -site "CoreSite"


utl::report "###############################################################################"
utl::report "# 01-03: Padring"
utl::report "###############################################################################"
source src/padring.tcl


##########################################################################
# RAM sizes
##########################################################################
set RamMaster512x32   [[ord::get_db] findMaster "RM_IHPSG13_1P_512x32_c2_bm_bist"]
set RamSize512x32_W   [ord::dbu_to_microns [$RamMaster512x32 getWidth]]
set RamSize512x32_H   [ord::dbu_to_microns [$RamMaster512x32 getHeight]]


##########################################################################
# Chip and Core Area
##########################################################################
# core gets snapped to site-grid -> get real values
set coreArea      [ord::get_core_area]
set core_leftX    [lindex $coreArea 0]
set core_bottomY  [lindex $coreArea 1]
set core_rightX   [lindex $coreArea 2]
set core_topY     [lindex $coreArea 3]


##########################################################################
# Tracks 
##########################################################################
# We need to define the metal tracks 
# (where the wires on each metal should go)
make_tracks

# the height of a standard cell, useful to align things
set siteHeight        [ord::dbu_to_microns [[dpl::get_row_site] getHeight]]


utl::report "###############################################################################"
utl::report "# 01-04: Macro Placement"
utl::report "###############################################################################"
# Paths to the instances of macros
utl::report "Macro Names"
source src/instances.tcl

# Placing macros
# use these for macro placement
set floorPaddingX      20.0
set floorPaddingY      20.0
set floor_leftX       [expr $core_leftX + $floorPaddingX]
set floor_bottomY     [expr $core_bottomY + $floorPaddingY]
set floor_rightX      [expr $core_rightX - $floorPaddingX]
set floor_topY        [expr $core_topY - $floorPaddingY]
set floor_midpointX   [expr $floor_leftX + ($floor_rightX - $floor_leftX)/2]
set floor_midpointY   [expr $floor_bottomY + ($floor_topY - $floor_bottomY)/2]
set sramHaloX          10.0
set sramHaloY          10.0

utl::report "Place Macros"

# Bank0: top-left, pins facing down
set bank0X $floor_leftX
set bankY [expr $floor_topY - $RamSize512x32_H]
placeInstance $bank0_sram0 $bank0X $bankY R0

# Bank1: top-right, pins facing down
set bank1X [expr $floor_rightX - $RamSize512x32_W]
placeInstance $bank1_sram0 $bank1X $bankY R0

utl::report "SRAM macro box: width ${RamSize512x32_W} height ${RamSize512x32_H}"
utl::report "SRAM bank0 bbox: ($bank0X, $bankY) - ([expr {$bank0X + $RamSize512x32_W}], [expr {$bankY + $RamSize512x32_H}]) R0"
utl::report "SRAM bank1 bbox: ($bank1X, $bankY) - ([expr {$bank1X + $RamSize512x32_W}], [expr {$bankY + $RamSize512x32_H}]) R0"
utl::report "SRAM horizontal gaps to core boundary: left [expr {$bank0X - $core_leftX}] between [expr {$bank1X - ($bank0X + $RamSize512x32_W)}] right [expr {$core_rightX - ($bank1X + $RamSize512x32_W)}]"
utl::report "SRAM vertical gap to core boundary: top [expr {$core_topY - ($bankY + $RamSize512x32_H)}]"
utl::report "SRAM row-cut halo: x $sramHaloX y $sramHaloY"

# defined in init_tech.tcl
insertTapCells

cut_rows -halo_width_x $sramHaloX -halo_width_y $sramHaloY
global_connect

# Save an image before PDN insertion. PDN channel-repair failures are easier to
# debug from the pure floorplan with rows already cut around fixed macros.
report_image "01-04_${proj_name}.pre_pdn" true


utl::report "###############################################################################"
utl::report "# 01-05: Power Grid"
utl::report "###############################################################################"
source scripts/power_grid_${pdk_name}.tcl

source /output/add_full_io_leads.tcl

write_def /output/precheck.def
write_db /output/precheck.odb
set block [ord::get_db_block]
dict for {name master} $initial_masters {
    set inst [$block findInst $name]
    if {$inst == "NULL" || [[$inst getMaster] getName] != $master} {error "Original functional instance changed: $name"}
}
dict for {key expected} $initial_signal_pins {
    lassign $key inst_name pin_name
    set term [[$block findInst $inst_name] findITerm $pin_name]
    if {$term == "NULL"} {error "Original pin missing: $key"}
    set net [$term getNet]
    set actual {UNCONNECTED}
    if {$net != "NULL"} {set actual [$net getName]}
    if {$actual != $expected} {error "Original signal connection changed: $key"}
}
dict for {name expected} $initial_ports {
    set port [$block findBTerm $name]
    if {$port == "NULL"} {error "Original top port missing: $name"}
    set actual [list [[$port getNet] getName] [$port getIoType] [$port getSigType]]
    if {$actual != $expected} {error "Original port changed: $name expected=$expected actual=$actual"}
}
set added [dict create]
set pg_count 0
foreach inst [$block getInsts] {
    set name [$inst getName]
    set master [[$inst getMaster] getName]
    if {![dict exists $initial_masters $name]} {
        if {$master != "bondpad70_m2_ring" && $master != "sg13g2_Corner" && ![string match sg13g2_Filler* $master]} {
            error "Unexpected added functional instance: $name $master"
        }
        dict incr added $master
    }
    foreach term [$inst getITerms] {
        set pin [[$term getMTerm] getName]
        set expected {}
        switch -- $pin {
            VDD - VDD! - VDDARRAY - VDDARRAY! - vdd {set expected VDD}
            VSS - VSS! - vss {set expected VSS}
            iovdd {set expected VDDIO}
            iovss {set expected VSSIO}
        }
        if {$expected != {}} {
            set net [$term getNet]
            if {$net == "NULL" || [$net getName] != $expected} {error "Missing or wrong explicit PG: $name $pin"}
            incr pg_count
        }
    }
}
set f [open /output/structural_summary.tsv w]
puts $f "metric\tvalue"
puts $f "original_instances\t[dict size $initial_masters]"
puts $f "original_signal_pins\t[dict size $initial_signal_pins]"
puts $f "original_top_ports\t[dict size $initial_ports]"
puts $f "explicit_pg_pins\t$pg_count"
puts $f "core_bbox_um\t[ord::get_core_area]"
puts $f "functional_connectivity_preserved\ttrue"
close $f
set f [open /output/io_instances.tsv w]
puts $f "name\tmaster\torientation\txmin\tymin\txmax\tymax"
set counts [dict create]
foreach inst [$block getInsts] {
    set master [[$inst getMaster] getName]
    dict incr counts $master
    if {[string match sg13g2_IOPad* $master] || [string match sg13g2_Filler* $master] || $master in {sg13g2_Corner bondpad70_m2_ring}} {
        set b [$inst getBBox]
        puts $f "[$inst getName]\t$master\t[$inst getOrient]\t[$b xMin]\t[$b yMin]\t[$b xMax]\t[$b yMax]"
    }
}
close $f
set f [open /output/master_areas.tsv w]
puts $f "master\ttype\tarea_um2\tcandidate_count"
foreach lib [[ord::get_db] getLibs] {
    foreach master [$lib getMasters] {
        set name [$master getName]
        set count 0
        if {[dict exists $counts $name]} {set count [dict get $counts $name]}
        puts $f "$name\t[$master getType]\t[expr {[$master getWidth]*double([$master getHeight])/1000000}]\t$count"
    }
}
close $f
puts {FULL_IO_FLOORPLAN_STRUCTURAL_CHECK_COMPLETE}

# Save checkpoint
save_checkpoint 01_${proj_name}.floorplan
report_image "01_${proj_name}.floorplan" true

utl::report "###############################################################################"
utl::report "# Stage 01 complete: Checkpoint saved to ${save_dir}/01_${proj_name}.floorplan.zip"
utl::report "###############################################################################"
