# SPDX-License-Identifier: Apache-2.0
# Append to a copied IHP custom_reader.lvs only. Exact X-model dispatch;
# no extraction, connection, reduction, or comparison changes.
module StrictTapXAdapter
  TAP_X_MODELS = %w[PTAP1 NTAP1].freeze
  TAP_X_PARAMETERS = %w[A P PERIM W L].freeze

  def wants_subcircuit(circuit_name)
    TAP_X_MODELS.include?(circuit_name.to_s.upcase) || super
  end

  def element(circuit, ele, name, model, value, nets, params)
    return super unless ele == 'X' && TAP_X_MODELS.include?(model.to_s.upcase)

    raise ArgumentError, 'tap X requires exactly two terminals (TIE, WELL)' unless nets.size == 2
    raise ArgumentError, 'tap X does not support nonunit .options scale' unless get_scale == 1.0
    mapped = (params || {}).dup
    unknown = mapped.keys - TAP_X_PARAMETERS
    raise ArgumentError, "unsupported tap X parameters: #{unknown.join(',')}" unless unknown.empty?
    mapped.each do |key, number|
      unless number.is_a?(Numeric) && number.finite? && number > 0
        raise ArgumentError, "tap X #{key} must be finite and positive"
      end
    end
    area = mapped['A'] || (mapped['W'] && mapped['L'] && mapped['W'] * mapped['L'])
    perimeter = mapped['P'] || mapped['PERIM'] || (mapped['W'] && mapped['L'] && 2 * (mapped['W'] + mapped['L']))
    raise ArgumentError, 'tap X requires area and perimeter or W/L' unless area && perimeter
    if mapped['P'] && mapped['PERIM'] && mapped['P'] != mapped['PERIM']
      raise ArgumentError, 'tap X P and PERIM disagree'
    end
    # The existing R path supplies CustomTap, ordered TIE/WELL, A*1e12 and P*1e6.
    process_device('R', circuit, name, model, nets, mapped)
    true
  end
end

CustomReader.prepend(StrictTapXAdapter)
