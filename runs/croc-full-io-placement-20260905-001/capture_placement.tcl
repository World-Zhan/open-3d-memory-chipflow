
proc capture_placement {stage} {
    set block [ord::get_db_block]
    write_def /output/${stage}.def
    write_verilog /output/${stage}.v
    write_sdc /output/${stage}.sdc
    set f [open /output/${stage}_instances.tsv w]
    puts $f "name\tmaster\ttype\torientation\tstatus\txmin\tymin\txmax\tymax"
    set p [open /output/${stage}_iterms.tsv w]
    puts $p "instance\tpin\tnet\tio_type\tsignal_type"
    set areas [dict create]
    foreach inst [$block getInsts] {
        set master [$inst getMaster]
        set box [$inst getBBox]
        puts $f "[$inst getName]\t[$master getName]\t[$master getType]\t[$inst getOrient]\t[$inst getPlacementStatus]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
        set kind [$master getType]
        if {![dict exists $areas $kind]} {dict set areas $kind 0.0}
        dict set areas $kind [expr {[dict get $areas $kind] + [$master getWidth]*double([$master getHeight])/1000000}]
        foreach term [$inst getITerms] {
            set mt [$term getMTerm]
            set net [$term getNet]
            set nn {UNCONNECTED}
            if {$net != "NULL"} {set nn [$net getName]}
            puts $p "[$inst getName]\t[$mt getName]\t$nn\t[$mt getIoType]\t[$mt getSigType]"
        }
    }
    close $f
    close $p
    set f [open /output/${stage}_bterms.tsv w]
    puts $f "port\tnet\tio_type\tsignal_type"
    set p [open /output/${stage}_bpin_boxes.tsv w]
    puts $p "port\tnet\tlayer\txmin\tymin\txmax\tymax\tstatus"
    foreach term [$block getBTerms] {
        set nn [[$term getNet] getName]
        puts $f "[$term getName]\t$nn\t[$term getIoType]\t[$term getSigType]"
        foreach pin [$term getBPins] {
            foreach box [$pin getBoxes] {
                puts $p "[$term getName]\t$nn\t[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]\t[$pin getPlacementStatus]"
            }
        }
    }
    close $f
    close $p
    set f [open /output/${stage}_area.tsv w]
    puts $f "type\tarea_um2"
    dict for {kind value} $areas {puts $f "$kind\t$value"}
    close $f
    set f [open /output/${stage}_bounds.tsv w]
    puts $f "region\tbbox_um"
    puts $f "die\t[ord::get_die_area]"
    puts $f "core\t[ord::get_core_area]"
    close $f
}

proc verify_placement_ports {} {
    set block [ord::get_db_block]
    if {[llength [$block getBTerms]] != 52} {error "Expected 52 original ports"}
    foreach {name kind} {VDD POWER VSS GROUND VDDIO POWER VSSIO GROUND} {
        set port [$block findBTerm $name]
        if {$port == "NULL" || [$port getSigType] != $kind || [[$port getNet] getName] != $name || [$port getIoType] != "INOUT"} {
            error "Invalid original PG port: $name"
        }
    }
}
