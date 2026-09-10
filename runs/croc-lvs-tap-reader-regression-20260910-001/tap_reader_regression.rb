# SPDX-License-Identifier: Apache-2.0
require 'json'
require 'logger'
# These accessors supply the two non-geometric globals consumed when loading
# the unmodified device definitions outside the LVS DSL.
def logger; @reader_logger ||= Logger.new($stdout); end
def dbu; 0.001; end
rules = '/output/deck/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks'
%w[globals custom_combiner custom_devices custom_reader].each { |file| load rules + '/' + file + '.lvs' }

def inventory(netlist)
  netlist.each_circuit.map do |circuit|
    {
      'name' => circuit.name,
      'pins' => circuit.each_pin.map { |p| p.name },
      'devices' => circuit.each_device.map do |device|
        klass = device.device_class
        { 'name' => device.name, 'class' => klass.name,
          'ruby_class' => klass.class.name,
          'terminals' => klass.terminal_definitions.to_h { |t| [t.name, device.net_for_terminal(t.id)&.name] },
          'parameters' => klass.parameter_definitions.to_h { |p| [p.name, device.parameter(p.id)] } }
      end,
      'subcircuits' => circuit.each_subcircuit.map do |sub|
        { 'name' => sub.name, 'circuit_ref' => sub.circuit_ref.name,
          'nets' => sub.circuit_ref.each_pin.map { |p| sub.net_for_pin(p.id)&.name } }
      end
    }
  end
end

cases = JSON.parse(File.read('/output/cases.json'))
results = {}
cases.each do |item|
  path = '/output/inputs/' + item['id'] + '.cdl'
  File.write(path, item['spice'])
  begin
    netlist = RBA::Netlist.new
    netlist.read(path, RBA::NetlistSpiceReader.new(CustomReader.new))
    results[item['id']] = { 'status' => 'read', 'inventory' => inventory(netlist) }
    netlist.write('/output/results/' + item['id'] + '.spice', RBA::NetlistSpiceWriter.new)
  rescue StandardError => e
    results[item['id']] = { 'status' => 'rejected', 'error_class' => e.class.name, 'error' => e.message }
  end
end
result = { 'schema_version' => 1, 'tool_version' => RBA::Application.instance.version,
           'cases' => results }
File.write('/output/results.json', JSON.pretty_generate(result) + "\n")
puts 'READER_CASES_COMPLETE count=' + results.size.to_s
