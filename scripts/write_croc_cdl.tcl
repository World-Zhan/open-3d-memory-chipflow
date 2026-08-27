# SPDX-License-Identifier: Apache-2.0

foreach variable {CROC_ODB CROC_CDL_OUT CROC_CDL_MASTERS} {
  if {![info exists ::env($variable)]} {
    error "$variable is required"
  }
}

read_db $::env(CROC_ODB)
set masters [split $::env(CROC_CDL_MASTERS) "|"]
write_cdl -masters $masters $::env(CROC_CDL_OUT)
puts "\[SIGNOFF\] wrote CDL $::env(CROC_CDL_OUT)"
