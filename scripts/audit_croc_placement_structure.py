#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Conservative placement connectivity audit; reads evidence and never runs EDA."""
import argparse
import csv
import hashlib
import json
import itertools
import re
from collections import Counter, defaultdict
from pathlib import Path

from validate_croc_clock_eco import parse_def, section

BUFFERS = {f'sg13g2_buf_{n}' for n in (1, 2, 4, 8, 16)}
TIES = {'sg13g2_tiehi': ('L_HI', '1'), 'sg13g2_tielo': ('L_LO', '0')}
PG = {'VDD': 'VDD', 'VDD!': 'VDD', 'VDDARRAY': 'VDD', 'VDDARRAY!': 'VDD',
      'vdd': 'VDD', 'VSS': 'VSS', 'VSS!': 'VSS', 'vss': 'VSS', 'iovdd': 'VDDIO', 'iovss': 'VSSIO'}
FLOATING = {'UNCONNECTED', 'NULL', ''}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def groups(text, kind, direct=False):
    """Read balanced Liberty groups, ignoring braces inside quoted strings."""
    pattern = re.compile(r'\b' + re.escape(kind) + r'\s*\(([^()]*)\)\s*\{')
    output = []
    depths = []
    depth, quoted, escaped = 0, False, False
    for char in text:
        depths.append(depth)
        if escaped:
            escaped = False
        elif char == '\\' and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            depth += (char == '{') - (char == '}')
    for match in pattern.finditer(text):
        if direct and depths[match.start()] != 0:
            continue
        depth, quoted, escaped, pos = 1, False, False, match.end()
        while depth and pos < len(text):
            char = text[pos]
            if escaped:
                escaped = False
            elif char == '\\' and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                depth += (char == '{') - (char == '}')
            pos += 1
        if depth:
            raise ValueError('Unterminated Liberty group')
        output.append((match[1].strip().strip('"'), text[match.end():pos - 1]))
    return output


def attribute(text, name):
    hits = re.findall(r'\b' + re.escape(name) + r'\s*:\s*("(?:[^"\\]|\\.)*"|[^;]+)\s*;', text)
    if len(hits) > 1:
        raise ValueError('Ambiguous Liberty logical attribute: ' + name)
    return re.sub(r'\s+', '', hits[0].strip().strip('"')) if hits else None


def liberty_logic(text):
    # Pinned IHP stdcell Liberty has scalar pin functions and ff/latch groups.
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    cells = {}
    for name, body in groups(text, 'cell'):
        if name in cells:
            raise ValueError('Duplicate Liberty cell')
        pins = {}
        for pin, pinbody in groups(body, 'pin', direct=True):
            if pin in pins:
                raise ValueError('Duplicate Liberty pin')
            pins[pin] = tuple(attribute(pinbody, key) for key in
                              ('direction', 'function', 'three_state', 'state_function', 'clock', 'signal_type'))
        sequential = tuple((kind, args, re.sub(r'\s+', '', payload))
                           for kind in ('ff', 'latch') for args, payload in groups(body, kind, direct=True))
        unsupported = bool(groups(body, 'statetable', direct=True) or groups(body, 'bus', direct=True) or groups(body, 'bundle', direct=True))
        signature = (tuple(sorted(pins.items())), sequential,
                     attribute(body, 'clock_gating_integrated_cell'))
        cells[name] = {'pins': pins, 'signature': signature, 'supported': not unsupported}
        cells[name]['symmetric_inputs'] = symmetric_inputs(cells[name])
    if not cells:
        raise ValueError('No Liberty cells')
    return cells


def boolean_function(expression, values):
    """Evaluate only an explicit scalar Liberty Boolean grammar; reject leftovers."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[01]|[!~'&*|+^()]", expression)
    if ''.join(tokens) != re.sub(r'\s+', '', expression):
        raise ValueError('Unsupported Liberty Boolean syntax')
    pos = 0
    def primary():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError('Incomplete Liberty function')
        token = tokens[pos]
        pos += 1
        if token in ('!', '~'):
            value = not primary()
        elif token == '(':
            value = binary(0)
            if pos >= len(tokens) or tokens[pos] != ')':
                raise ValueError('Unbalanced Liberty function')
            pos += 1
        elif token in ('0', '1'):
            value = token == '1'
        elif token in values:
            value = values[token]
        else:
            raise ValueError('Unknown Liberty Boolean identifier: ' + token)
        while pos < len(tokens) and tokens[pos] == "'":
            value = not value
            pos += 1
        return value
    precedence = {'|': 0, '+': 0, '^': 1, '&': 2, '*': 2}
    def binary(minimum):
        nonlocal pos
        left = primary()
        while pos < len(tokens) and precedence.get(tokens[pos], -1) >= minimum:
            operator = tokens[pos]
            pos += 1
            right = binary(precedence[operator] + 1)
            left = (left or right) if operator in ('|', '+') else ((left and right) if operator in ('&', '*') else left != right)
        return left
    result = binary(0)
    if pos != len(tokens):
        raise ValueError('Unparsed Liberty Boolean tokens')
    return result


def symmetric_inputs(cell):
    """Prove pairwise Boolean input permutations by exhaustive truth tables."""
    pins = cell['pins']
    inputs = sorted(pin for pin, attrs in pins.items() if attrs[0] == 'input')
    identity = {pin: (pin,) for pin in inputs}
    if not cell['supported'] or cell['signature'][1] or cell['signature'][2] or len(inputs) > 10:
        return identity
    outputs = [attrs[1] for attrs in pins.values() if attrs[0] == 'output']
    if not outputs or any(value is None for value in outputs) or any(any(attrs[2:]) or attrs[0] not in ('input', 'output') for attrs in pins.values()):
        return identity
    assignments = [dict(zip(inputs, bits)) for bits in itertools.product((False, True), repeat=len(inputs))]
    try:
        truth = [tuple(boolean_function(expr, values) for expr in outputs) for values in assignments]
        equivalent = {pin: {pin} for pin in inputs}
        for first, second in itertools.combinations(inputs, 2):
            swapped = [dict(values, **{first: values[second], second: values[first]}) for values in assignments]
            if truth == [tuple(boolean_function(expr, values) for expr in outputs) for values in swapped]:
                equivalent[first].add(second)
                equivalent[second].add(first)
        # Pair transposition symmetry is an equivalence relation; fail closed if not.
        if any(equivalent[a] != equivalent[b] for a in inputs for b in equivalent[a]):
            raise ValueError('Nontransitive symmetry proof')
        return {pin: tuple(sorted(group)) for pin, group in equivalent.items()}
    except ValueError:
        return identity


def cell_kind(master, library):
    if master not in BUFFERS and master not in TIES:
        return 'retained'
    cell = library.get(master)
    if not cell or not cell['supported'] or cell['signature'][1]:
        raise ValueError('Unsupported buffer/tie Liberty model: ' + master)
    pins = cell['pins']
    if master in BUFFERS:
        expected = {'A': ('input', None), 'X': ('output', 'A')}
    else:
        pin, value = TIES[master]
        expected = {pin: ('output', value)}
    if set(pins) != set(expected) or any(pins[p][:2] != value or any(pins[p][2:]) for p, value in expected.items()):
        raise ValueError('Buffer/tie function or pin contract changed: ' + master)
    return 'buffer' if master in BUFFERS else 'tie'


def unique(rows, key):
    output = {}
    for row in rows:
        name = tuple(row[k] for k in key)
        if name in output:
            raise ValueError('Duplicate exported identity: ' + str(name))
        output[name] = row
    return output


def normalize(instances, iterms, bterms, library, trace=None):
    cells = unique(instances, ('name',))
    terms = unique(iterms, ('instance', 'pin'))
    ports = unique(bterms, ('port',))
    kinds = {name: cell_kind(row['master'], library) for (name,), row in cells.items()}
    pinsets = defaultdict(set)
    parent, drivers = {}, defaultdict(list)
    def find(net):
        parent.setdefault(net, net)
        while parent[net] != net:
            parent[net] = parent[parent[net]]
            net = parent[net]
        return net
    def join(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[a] = b
    for (name, pin), term in terms.items():
        if (name,) not in cells:
            raise ValueError('Unknown ITerm instance')
        pinsets[name].add(pin)
        if term['signal_type'] in ('POWER', 'GROUND') or pin in PG:
            if pin not in PG or term['net'] != PG[pin]:
                raise ValueError('Missing/wrong explicit supply: ' + name + '/' + pin)
            expected_type = 'GROUND' if PG[pin] in ('VSS', 'VSSIO') else 'POWER'
            if term['signal_type'] != expected_type:
                raise ValueError('Wrong supply pin type')
            continue
        if term['io_type'] not in ('INPUT', 'OUTPUT', 'INOUT'):
            raise ValueError('Unknown pin direction')
        if term['net'] not in FLOATING:
            find(term['net'])
            if term['io_type'] in ('OUTPUT', 'INOUT'):
                drivers[term['net']].append((name, pin))
    for (name,), row in cells.items():
        if row['type'] == 'CORE' and not {'VDD', 'VSS'} <= pinsets[name]:
            raise ValueError('CORE instance missing exported supply pins: ' + name)
        if row['master'] in library:
            expected = set(library[row['master']]['pins'])
            actual = pinsets[name] - set(PG)
            if actual != expected:
                raise ValueError('Incomplete Liberty signal pin inventory: ' + name)
            for pin in expected:
                if terms[name, pin]['io_type'].lower() != library[row['master']]['pins'][pin][0]:
                    raise ValueError('Exported pin direction differs from Liberty')
    for (port,), row in ports.items():
        if row['net'] in FLOATING:
            raise ValueError('Unconnected top port')
        find(row['net'])
        if row['io_type'] in ('INPUT', 'INOUT') and row['signal_type'] not in ('POWER', 'GROUND'):
            drivers[row['net']].append(('PIN', port))
    edges = {}
    constants = []
    for (name,), row in cells.items():
        kind = kinds[name]
        if kind == 'buffer':
            src, dst = terms[name, 'A']['net'], terms[name, 'X']['net']
            if src in FLOATING or dst in FLOATING or src == dst:
                raise ValueError('Floating/self-loop transparent buffer')
            if drivers[dst] != [(name, 'X')]:
                raise ValueError('Multiple/unknown driver on buffer output')
            if dst in edges:
                raise ValueError('Duplicated buffer output net')
            edges[dst] = src
        elif kind == 'tie':
            pin, value = TIES[row['master']]
            net = terms[name, pin]['net']
            if net in FLOATING:
                raise ValueError('Floating tie output is not covered')
            if any(kinds.get(driver) != 'tie' for driver, _ in drivers[net]):
                raise ValueError('Nonconstant co-driver on tie net')
            constants.append((net, value))
    # A directed cycle is not a wire, even if undirected union would hide it.
    done = set()
    for start in edges:
        path, node = set(), start
        while node in edges and node not in done:
            if node in path:
                raise ValueError('Transparent buffer cycle')
            path.add(node)
            node = edges[node]
        done.update(path)
    for dst, src in edges.items():
        join(dst, src)
    for net, value in constants:
        join(net, ('constant', value))
    if find(('constant', '0')) == find(('constant', '1')):
        raise ValueError('Mixed constant values on one net')
    components = defaultdict(list)
    for (name, pin), term in terms.items():
        if kinds[name] != 'retained' or pin in PG or term['signal_type'] in ('POWER', 'GROUND'):
            continue
        net = term['net'] if term['net'] not in FLOATING else ('floating', name, pin)
        model = library.get(cells[name,]['master'], {})
        label = model.get('symmetric_inputs', {}).get(pin, (pin,))
        components[find(net)].append(('ITERM', name, label, term['io_type'], term['signal_type']))
    for (port,), row in ports.items():
        components[find(row['net'])].append(('BTERM', port, row['io_type'], row['signal_type']))
    for value in ('0', '1'):
        components[find(('constant', value))].append(('CONSTANT', value))
    normalized = {net: frozenset(Counter(v).items()) for net, v in components.items() if v}
    if trace is not None:
        for (name, pin), term in terms.items():
            model = library.get(cells[name,]['master'], {})
            if kinds[name] == 'retained' and len(model.get('symmetric_inputs', {}).get(pin, (pin,))) > 1:
                trace[name, pin] = normalized[find(term['net'] if term['net'] not in FLOATING else ('floating', name, pin))]
    return set(normalized.values()), kinds


def compare_logic(before, after, library):
    btrace, atrace = {}, {}
    bgraph, bkinds = normalize(*before, library, trace=btrace)
    agraph, akinds = normalize(*after, library, trace=atrace)
    bcells = {r['name']: r for r in before[0] if bkinds[r['name']] == 'retained'}
    acells = {r['name']: r for r in after[0] if akinds[r['name']] == 'retained'}
    if set(bcells) != set(acells):
        raise ValueError('Unverified functional instance add/remove/clone: ' + str(sorted(set(bcells) ^ set(acells))[:8]))
    replacements = []
    for name, row in bcells.items():
        old, new = row['master'], acells[name]['master']
        if row['type'] != acells[name]['type']:
            raise ValueError('Original master type changed')
        if old != new:
            if row['type'] != 'CORE' or old not in library or new not in library:
                raise ValueError('Unverified nonstandard master replacement')
            if not library[old]['supported'] or not library[new]['supported'] or library[old]['signature'] != library[new]['signature']:
                raise ValueError('Master logical/sequential signature differs: ' + name)
            replacements.append({'instance': name, 'before_master': old, 'after_master': new})
    if bgraph != agraph:
        raise ValueError('Connectivity changed after buffer/tie and proven symmetric-input normalization: ' +
                         str({'before_only_components': len(bgraph - agraph), 'after_only_components': len(agraph - bgraph),
                              'before_examples': sorted(map(repr, bgraph - agraph))[:6],
                              'after_examples': sorted(map(repr, agraph - bgraph))[:6]}))
    swapped_instances = sorted({name for (name, pin), net in btrace.items() if atrace.get((name, pin)) != net})
    return {'result': 'PASS', 'observed_symmetric_input_permutation_instances': swapped_instances,
            'observed_symmetric_input_permutation_count': len(swapped_instances),
            'symmetric_input_groups_proven_by': 'exhaustive_actual_scalar_Liberty_truth_tables',
            'retained_instances': len(bcells), 'logic_equivalent_master_replacements': replacements,
            'before_transparent_buffers': sum(v == 'buffer' for v in bkinds.values()),
            'after_transparent_buffers': sum(v == 'buffer' for v in akinds.values()),
            'before_ties': sum(v == 'tie' for v in bkinds.values()), 'after_ties': sum(v == 'tie' for v in akinds.values())}


def physical_check(before, after, bpins, apins, bdef, adef):
    bcells, acells = (unique(x[0], ('name',)) for x in (before, after))
    protected = {k: v for k, v in bcells.items() if v['type'] != 'CORE'}
    expected_after = {k: v for k, v in acells.items() if v['type'] != 'CORE'}
    if protected != expected_after:
        raise ValueError('Fixed IO/bondpad/SRAM instance geometry, identity, status or master changed')
    macros = [r for r in protected.values() if r['type'] == 'BLOCK']
    io = [r for r in protected.values() if r['type'] != 'BLOCK']
    if len(macros) != 2 or len(io) != 192:
        raise ValueError('Require the original 2 SRAM and 192 IO physical instances')
    bports, aports = (unique(x[2], ('port',)) for x in (before, after))
    def protected_pg(data):
        return {(r['instance'], r['pin']): r for r in data[1]
                if (r['instance'],) in protected and (r['pin'] in PG or r['signal_type'] in ('POWER', 'GROUND'))}
    if protected_pg(before) != protected_pg(after):
        raise ValueError('Protected IO/SRAM supply terminal inventory changed')
    if bports != aports or len(bports) != 52:
        raise ValueError('Original 52 top port signatures changed')
    def inventory(rows):
        return Counter(tuple(sorted(row.items())) for row in rows)
    if inventory(bpins) != inventory(apins) or len(bpins) != 64:
        raise ValueError('Original 64 physical top pin boxes changed')
    if {p['port'] for p in bpins} != {k[0] for k in bports}:
        raise ValueError('Physical top port coverage incomplete')
    def boundary(text):
        _, _, die = parse_def(text)
        rows = tuple(re.findall(r'^ROW\s+.*?;', text, re.M))
        tracks = tuple(re.findall(r'^TRACKS\s+.*?;', text, re.M))
        if not rows or not tracks:
            raise ValueError('Missing actual core rows or routing tracks')
        return die, rows, tracks
    if boundary(bdef) != boundary(adef):
        raise ValueError('Die, core row geometry or routing tracks changed')
    def special_shapes(text):
        # Connectivity prefixes can legitimately gain buffer/tie supply pins.
        return {name: body[body.find('+'):] if '+' in body else '' for name, body in section(text, 'SPECIALNETS')}
    bshapes, ashapes = special_shapes(bdef), special_shapes(adef)
    if set(bshapes) != set(ashapes):
        raise ValueError('Special net inventory changed')
    uses = []
    for net, old in bshapes.items():
        new = ashapes[net]
        if old != new:
            # OpenROAD marks input clock leads CLOCK during placement. Preserve
            # every shape/property byte and record this exact classification change.
            if not (old.startswith('+ USE SIGNAL') and new == old.replace('+ USE SIGNAL', '+ USE CLOCK', 1)
                    and any(row['net'] == net and row['io_type'] == 'INPUT' for row in bports.values())):
                raise ValueError('PG or external IO lead special-wire geometry/properties changed')
            uses.append({'net': net, 'before': 'SIGNAL', 'after': 'CLOCK'})
    return {'result': 'PASS', 'protected_io_instances': 192, 'protected_sram_instances': 2,
            'top_ports': 52, 'physical_top_pin_boxes': 64, 'die_rows_tracks_and_special_wires_preserved': True,
            'protected_pg_inventory_preserved': True, 'input_lead_use_changes': uses}


def def_export_check(instances, iterms, bterms, text):
    cells, nets, _ = parse_def(text)
    if cells != {r['name']: r['master'] for r in instances}:
        raise ValueError('DEF and instance export differ')
    net_pins = {pin: net for net, pins in nets.items() for pin in pins if pin[0] != '*'}
    # DEF's (* VDD) encodes supply connections, not missing explicit OpenDB ITerms.
    # Expand only actual captured terminals of that exact pin name, and verify PG.
    wildcard_targets = {}
    for net, pins in nets.items():
        for inst, pin in pins:
            if inst == '*':
                if pin not in PG or PG[pin] != net:
                    raise ValueError('Unsupported or wrong-net DEF wildcard')
                if pin in wildcard_targets and wildcard_targets[pin] != net:
                    raise ValueError('Ambiguous DEF wildcard')
                wildcard_targets[pin] = net
    explicit_count = len(net_pins)
    for term in iterms:
        if term['pin'] in wildcard_targets:
            key = (term['instance'], term['pin'])
            target = wildcard_targets[term['pin']]
            if key in net_pins and net_pins[key] != target:
                raise ValueError('DEF wildcard conflicts with explicit pin connection')
            net_pins[key] = target
    if sum(len([p for p in pins if p[0] != '*']) for pins in nets.values()) != explicit_count:
        raise ValueError('DEF pin appears on multiple nets')
    expected = {(r['instance'], r['pin']): r['net'] for r in iterms if r['net'] not in FLOATING}
    expected.update({('PIN', r['port']): r['net'] for r in bterms})
    if net_pins != expected:
        raise ValueError('DEF and complete terminal export connectivity differ')
    return {'result': 'PASS', 'explicit_terminals': explicit_count,
            'actual_exported_pg_terminals_expanded_from_def_wildcards': len(net_pins) - explicit_count}


def terminal_check(manifest, observation):
    if type(manifest.get('returncode')) is not int or manifest['returncode'] != 0 or manifest.get('status') != 'completed':
        raise ValueError('Require completed execution with real integer exit 0')
    state = observation.get('state', {})
    if (type(observation.get('state_returncode')) is not int or observation['state_returncode'] != 0
            or state != manifest.get('terminal_container_state')
            or state.get('Status') != 'exited' or state.get('Running') is not False
            or state.get('OOMKilled') is not False or state.get('Error') != ''
            or type(state.get('ExitCode')) is not int or state['ExitCode'] != 0
            or manifest.get('outer_timeout_expired') is not False):
        raise ValueError('Missing, inconsistent, nonterminal or failed actual container state')
    return {'result': 'PASS', 'returncode': 0, 'container_status': 'exited', 'oom_killed': False}


def audit(root, run_id):
    run = root / 'runs' / run_id
    manifest = json.loads((run / 'manifest.json').read_text())
    hashes = {str((run / 'manifest.json').relative_to(root)): sha(run / 'manifest.json')}
    required = {phase + suffix for phase in ('before', 'after') for suffix in
                ('.def', '.v', '_instances.tsv', '_iterms.tsv', '_bterms.tsv', '_bpin_boxes.tsv', '_bounds.tsv')}
    required |= {'terminal_observation.json', 'tool.log'}
    if not required <= set(manifest.get('outputs_sha256', {})):
        raise ValueError('Missing required hash-bound actual exports')
    for field, base in [('source_sha256', root), ('outputs_sha256', run), ('generated_inputs_sha256', run)]:
        if not isinstance(manifest.get(field), dict) or not manifest[field]:
            raise ValueError('Missing input/output hash inventory: ' + field)
        for rel, expected in manifest[field].items():
            path = base / rel
            if sha(path) != expected:
                raise ValueError('Manifest hash mismatch: ' + str(path))
            hashes[str(path.relative_to(root))] = expected
    execution = terminal_check(manifest, json.loads((run / 'terminal_observation.json').read_text()))
    lib = root / 'upstream/croc/technology/lib/sg13g2_stdcell_typ_1p20V_25C.lib'
    hashes[str(lib.relative_to(root))] = sha(lib)
    hashes['scripts/audit_croc_placement_structure.py'] = sha(root / 'scripts/audit_croc_placement_structure.py')
    library = liberty_logic(lib.read_text())
    exports = {}
    crosschecks = {}
    for phase in ('before', 'after'):
        exports[phase] = []
        for kind in ('instances', 'iterms', 'bterms', 'bpin_boxes'):
            path = run / (phase + '_' + kind + '.tsv')
            hashes[str(path.relative_to(root))] = sha(path)
            with path.open() as handle:
                exports[phase].append(list(csv.DictReader(handle, delimiter='\t')))
        for suffix in ('def', 'v'):
            path = run / (phase + '.' + suffix)
            hashes[str(path.relative_to(root))] = sha(path)
        crosschecks[phase] = def_export_check(*exports[phase][:3], (run / (phase + '.def')).read_text())
    before, after = exports['before'], exports['after']
    report = {'run_id': run_id, 'classification': 'conservative_placement_structure_not_formal_or_signoff',
              'source_sha256': hashes, 'execution': execution, 'def_export_crosschecks': crosschecks, 'full_formal_equivalence_proven': False,
              'physical_placement_legality_proven': False, 'electrical_or_signoff_proven': False}
    for phase in ('before', 'after'):
        path = run / (phase + '_bounds.tsv')
        hashes[str(path.relative_to(root))] = sha(path)
    if (run / 'before_bounds.tsv').read_bytes() != (run / 'after_bounds.tsv').read_bytes():
        raise ValueError('Actual die/core bounds export changed')
    try:
        report['physical_invariants'] = physical_check(before[:3], after[:3], before[3], after[3],
                                                        (run / 'before.def').read_text(), (run / 'after.def').read_text())
    except ValueError as error:
        report['physical_invariants'] = {'result': 'UNVERIFIED', 'reason': str(error)}
    bmap, amap = ({row['name']: row['master'] for row in data[0]} for data in (before, after))
    report['snapshot_delta'] = {'before_instances': len(bmap), 'after_instances': len(amap),
        'added_by_master': dict(Counter(amap[n] for n in set(amap) - set(bmap))),
        'removed_by_master': dict(Counter(bmap[n] for n in set(bmap) - set(amap))),
        'existing_instances_with_changed_master': sum(bmap[n] != amap[n] for n in set(bmap) & set(amap))}
    try:
        report['normalized_connectivity'] = compare_logic(before[:3], after[:3], library)
    except ValueError as error:
        report['normalized_connectivity'] = {'result': 'UNVERIFIED', 'reason': str(error)}
    report['overall_result'] = 'PASS' if all(report[key]['result'] == 'PASS' for key in ('physical_invariants', 'normalized_connectivity')) else 'UNVERIFIED'
    report['limitations'] = ['Fixed IHP scalar Liberty logic only; buffer/tie normalization and exhaustively proven combinational input symmetries; unsupported functional clones or rewrites are rejected.',
                              'Sequential cell identity and complete logical/state signatures are preserved; analog timing, X/Z behavior and waveform equivalence are not proven.',
                              'DEF and actual OpenDB exports are cross-checked; saved Verilog is hash-bound but not separately proven formally.']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / args.output
    if output.exists():
        raise ValueError('Preserve previous audit; use an independent output')
    try:
        result = audit(root, args.run_id)
    except (ValueError, KeyError, FileNotFoundError) as error:
        result = {'run_id': args.run_id, 'classification': 'conservative_placement_structure_not_formal_or_signoff',
                  'overall_result': 'UNVERIFIED', 'reason': str(error), 'full_formal_equivalence_proven': False,
                  'source_sha256': {'scripts/audit_croc_placement_structure.py': sha(root / 'scripts/audit_croc_placement_structure.py')}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha256'}, indent=2))
    raise SystemExit(0 if result['overall_result'] == 'PASS' else 1)
