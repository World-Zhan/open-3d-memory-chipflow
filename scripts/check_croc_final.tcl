# SPDX-License-Identifier: Apache-2.0

if {![info exists ::env(CROC_ODB)]} {
  error "CROC_ODB is required"
}
if {![info exists ::env(CROC_ACCEPTANCE_REPORT)]} {
  error "CROC_ACCEPTANCE_REPORT is required"
}

read_db $::env(CROC_ODB)
set report [open $::env(CROC_ACCEPTANCE_REPORT) w]

if {![design_is_routed]} {
  puts $report "design_is_routed=0"
  close $report
  error "Design has unrouted nets."
}
puts $report "design_is_routed=1"

foreach net {VDD VSS} {
  set rc [catch {check_power_grid -net $net} message]
  if {$rc != 0} {
    puts $report "power_grid_${net}=0"
    puts $report "power_grid_${net}_error=$message"
    close $report
    error "Power grid $net is disconnected: $message"
  }
  puts $report "power_grid_${net}=1"
}

close $report
puts {[ACCEPTANCE] Croc design_is_routed=1 VDD=connected VSS=connected}
