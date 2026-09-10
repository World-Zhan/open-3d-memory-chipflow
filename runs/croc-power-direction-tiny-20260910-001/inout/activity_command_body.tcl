
  parse_key_args "set_power_activity" args  keys {-input_ports -pins -activity -density -duty -clock}  flags {-global -input}

  check_argc_eq0 "set_power_activity" $args
  if { [info exists keys(-activity)] && [info exists keys(-density)]  || ![info exists keys(-activity)] && ![info exists keys(-density)] } {
    sta_error 306 "Specify -activity or -density."
  }

  set density 0.0
  if { [info exists keys(-activity)] } {
    set activity $keys(-activity)
    check_positive_float "activity" $activity
    if { [info exists keys(-clock)] } {
      set clk [get_clock_warn "-clock" $keys(-clock)]
    } else {
      set clks [get_clocks]
      if { $clks == {} } {
        sta_error 307 "-activity requires a clock to be defined"
      }
    }
    set density [expr $activity / [clock_min_period]]
  }

  if { [info exists keys(-density)] } {
    set density $keys(-density)
    check_positive_float "density" $density
    set density [expr $density / [time_ui_sta 1.0]]
    if { [info exists keys(-clock)] } {
      sta_warn 308 "-clock ignored for -density"
    }
  }
  set duty 0.5
  if { [info exists keys(-duty)] } {
    set duty $keys(-duty)
    check_float "duty" $duty
    if { $duty < 0.0 || $duty > 1.0 } {
      sta_error 309 "duty should be 0.0 to 1.0"
    }
  }

  if { [info exists flags(-global)] } {
    set_power_global_activity $density $duty
  }
  if { [info exists flags(-input)] } {
    set_power_input_activity $density $duty
  }
  if { [info exists keys(-input_ports)] } {
    set ports [get_ports_error "input_ports" $keys(-input_ports)]
    foreach port $ports {
      if { [get_property $port "direction"] == "input" } {
	if { [is_clock_src [sta::get_port_pin $port]] } {
          sta_warn 310 "activity cannot be set on clock ports."
        } else {
          set_power_input_port_activity $port $density $duty
        }
      }
    }
  }
  if { [info exists keys(-pins)] } {
    set pins [get_pins $keys(-pins)]
    foreach pin $pins {
      set_power_pin_activity $pin $density $duty
    }
  }

