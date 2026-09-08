# SPDX-License-Identifier: Apache-2.0
# Observation only: do not request the LVS engine's lazy netlist here.
require 'json'
require 'digest'

stage_inventory = lambda do |observed_netlist|
  circuits = []
  observed_netlist.each_circuit do |circuit|
    nets = []
    circuit.each_net do |net|
      pins = []
      net.each_pin { |ref| pins << { 'id' => ref.pin_id, 'name' => ref.pin.name } }
      terminals = []
      net.each_terminal do |ref|
        terminals << { 'device_id' => ref.device.id, 'device_name' => ref.device.name,
                       'class' => ref.device_class.name, 'terminal_id' => ref.terminal_id,
                       'terminal_name' => ref.terminal_def.name }
      end
      subpins = []
      net.each_subcircuit_pin do |ref|
        subpins << { 'subcircuit_id' => ref.subcircuit.id, 'pin_id' => ref.pin_id,
                     'pin_name' => ref.pin.name }
      end
      nets << { 'ordinal' => nets.length, 'name' => net.name, 'expanded_name' => net.expanded_name,
                'cluster_id' => net.cluster_id, 'pins' => pins, 'terminals' => terminals,
                'subcircuit_pins' => subpins }
    end
    pins = []
    circuit.each_pin do |pin|
      net = circuit.net_for_pin(pin.id)
      pins << { 'id' => pin.id, 'name' => pin.name, 'net_name' => net.nil? ? nil : net.name,
                'net_cluster_id' => net.nil? ? nil : net.cluster_id }
    end
    devices = []
    circuit.each_device do |device|
      klass = device.device_class
      terminals = klass.terminal_definitions.map do |term|
        net = device.net_for_terminal(term.id)
        { 'id' => term.id, 'name' => term.name, 'net_name' => net.nil? ? nil : net.name,
          'net_cluster_id' => net.nil? ? nil : net.cluster_id }
      end
      parameters = klass.parameter_definitions.map do |param|
        { 'id' => param.id, 'name' => param.name, 'value' => device.parameter(param.id) }
      end
      devices << { 'id' => device.id, 'name' => device.name, 'class' => klass.name,
                   'terminals' => terminals, 'parameters' => parameters }
    end
    subcircuits = []
    circuit.each_subcircuit do |sub|
      subpins = []
      sub.circuit_ref.each_pin do |pin|
        net = sub.net_for_pin(pin.id)
        subpins << { 'id' => pin.id, 'name' => pin.name, 'net_name' => net.nil? ? nil : net.name,
                     'net_cluster_id' => net.nil? ? nil : net.cluster_id }
      end
      subcircuits << { 'id' => sub.id, 'name' => sub.name, 'circuit_ref' => sub.circuit_ref.name,
                      'pins' => subpins }
    end
    circuits << { 'name' => circuit.name, 'nets' => nets, 'pins' => pins,
                  'devices' => devices, 'subcircuits' => subcircuits }
  end
  { 'circuits' => circuits }
end

stage_snapshot = lambda do |observed_netlist, stage|
  raise 'unsafe stage identifier' unless stage.match?(/\A[a-zA-Z0-9_-]+\z/)
  prefix = '/output/snapshots/' + stage
  before = stage_inventory.call(observed_netlist)
  before_json = JSON.generate(before)
  File.write(prefix + '.txt', observed_netlist.to_s)
  observed_netlist.write(prefix + '.spice', RBA::NetlistSpiceWriter.new)
  after_json = JSON.generate(stage_inventory.call(observed_netlist))
  unchanged = before_json == after_json
  record = { 'schema_version' => 1, 'stage' => stage,
             'observation_preserved_inventory' => unchanged,
             'before_sha256' => Digest::SHA256.hexdigest(before_json),
             'after_sha256' => Digest::SHA256.hexdigest(after_json), 'inventory' => before }
  File.write(prefix + '.inventory.json', JSON.pretty_generate(record) + "\n")
  raise 'observation mutated netlist inventory at ' + stage unless unchanged
  puts 'STAGE_SNAPSHOT ' + stage + ' inventory_preserved=true'
end
