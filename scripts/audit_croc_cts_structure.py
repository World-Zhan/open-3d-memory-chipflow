#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit actual CTS load cells, connectivity and CLOCK/NDR metadata without EDA."""
import argparse
import csv
import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import audit_croc_placement_structure as base


def net_properties(text):
    props = {}
    for net, body in base.section(text, 'NETS'):
        use = re.findall(r'\+ USE\s+(\S+)', body)
        ndr = re.findall(r'\+ NONDEFAULTRULE\s+(\S+)', body)
        if len(use) > 1 or len(ndr) > 1:
            raise ValueError('Ambiguous net use or NDR')
        props[net] = (use[0] if use else None, ndr[0] if ndr else None)
    rules = dict(base.section(text, 'NONDEFAULTRULES')) if re.search(r'^NONDEFAULTRULES\s', text, re.M) else {}
    rules = {name: ' '.join(body.split()) for name, body in rules.items()}
    return props, rules


def abstract_unobserved_loads(before, after, library, after_def):
    """Only newly added clock-load cells with no observable output are abstracted.

    This is a 2-state connectivity proof. Input capacitance, power, physical
    devices and waveform effects remain in the actual checkpoint for signoff.
    """
    prior = {row['name'] for row in before[0]}
    terms = base.unique(after[1], ('instance', 'pin'))
    _, nets, _ = base.parse_def(after_def)
    props, _ = net_properties(after_def)
    by_instance = defaultdict(dict)
    for (name, pin), row in terms.items():
        by_instance[name][pin] = row
    loads = []
    for row in after[0]:
        name, master = row['name'], row['master']
        if not re.fullmatch(r'clkload[0-9]+', name):
            continue
        if name in prior or row['type'] != 'CORE':
            raise ValueError('Clock load must be a newly added CORE instance')
        model = library.get(master)
        if not model or not model['supported'] or model['signature'][1] or model['signature'][2]:
            raise ValueError('Clock load must have a supported stateless Liberty model')
        logical = model['pins']
        inputs = [p for p, attrs in logical.items() if attrs[0] == 'input']
        outputs = [p for p, attrs in logical.items() if attrs[0] == 'output']
        if len(inputs) != 1 or len(outputs) != 1 or len(logical) != 2 or any(any(attrs[2:]) for attrs in logical.values()):
            raise ValueError('Clock load must be scalar input/output with no state or three-state behavior')
        inp, out = inputs[0], outputs[0]
        expr = logical[out][1]
        if expr is None:
            raise ValueError('Missing load output function')
        for bit in (False, True):
            base.boolean_function(expr, {inp: bit})
        exported = by_instance[name]
        if set(exported) != {inp, out, 'VDD', 'VSS'}:
            raise ValueError('Incomplete load pin inventory')
        for pin, net, kind in (('VDD', 'VDD', 'POWER'), ('VSS', 'VSS', 'GROUND')):
            if exported[pin]['net'] != net or exported[pin]['signal_type'] != kind or exported[pin]['io_type'] != 'INOUT':
                raise ValueError('Missing or wrong load explicit PG')
        if exported[inp]['io_type'] != 'INPUT' or exported[out]['io_type'] != 'OUTPUT' or any(exported[p]['signal_type'] != 'SIGNAL' for p in (inp, out)):
            raise ValueError('Clock load directions differ from actual Liberty')
        source, target = exported[inp]['net'], exported[out]['net']
        if source in base.FLOATING or props.get(source, (None,))[0] != 'CLOCK':
            raise ValueError('Load input is not on an observed CLOCK net')
        if target not in base.FLOATING:
            raise ValueError('Clock load output has a connection; abstraction forbidden')
        if any((name, out) in pins for pins in nets.values()):
            raise ValueError('Export says floating but DEF connects load output')
        if (name, inp) not in nets.get(source, set()):
            raise ValueError('Load input missing from actual DEF net')
        loads.append({'instance': name, 'master': master, 'input_pin': inp, 'input_net': source,
                      'output_pin': out, 'output_net': target, 'actual_liberty_function': expr})
    names = {row['instance'] for row in loads}
    filtered = [[row for row in after[0] if row['name'] not in names],
                [row for row in after[1] if row['instance'] not in names], after[2]]
    return filtered, loads


def prove_cts_logic(before, after, library):
    """Explicitly prove one-to-one inverter rename and scalar delay identity.

    In-memory aliases are only proof variables; actual netlists/master cells,
    area, timing and checkpoint bytes are untouched.
    """
    candidate = copy.deepcopy(after)
    prior = {row['name']: row for row in before[0]}
    actual = {row['name']: row for row in after[0]}
    delays = []
    for row in candidate[0]:
        if row['name'] in prior or not row['master'].startswith('sg13g2_dlygate'):
            continue
        model = library.get(row['master'])
        reference = library.get('sg13g2_buf_1')
        if (row['type'] != 'CORE' or not model or not reference or not model['supported']
                or model['signature'] != reference['signature']):
            raise ValueError('Hold delay is not identical scalar non-inverting Liberty logic')
        base.cell_kind('sg13g2_buf_1', library)
        delays.append({'instance': row['name'], 'actual_master': row['master'],
                       'proof_identity_master': 'sg13g2_buf_1', 'actual_function': model['pins']['X'][1]})
        row['master'] = 'sg13g2_buf_1'
    missing = sorted(set(prior) - set(actual))
    added = set(actual) - set(prior)
    aliases = []
    used = set()
    for old in missing:
        model = library.get(prior[old]['master'])
        if not model or not model['supported'] or model['signature'][1] or set(model['pins']) != {'A', 'Y'}:
            continue
        if (model['pins']['A'][:2] != ('input', None) or model['pins']['Y'][0] != 'output'
                or any(any(attrs[2:]) for attrs in model['pins'].values())
                or [base.boolean_function(model['pins']['Y'][1], {'A': bit}) for bit in (False, True)] != [True, False]):
            continue
        matches = [new for new in added if re.fullmatch(re.escape(old) + r'_[0-9]+', new)
                   and actual[new]['type'] == prior[old]['type'] == 'CORE'
                   and library.get(actual[new]['master'], {}).get('signature') == model['signature']]
        if len(matches) != 1 or matches[0] in used:
            raise ValueError('Inverter rename is not a unique one-to-one exact-function mapping')
        new = matches[0]
        used.add(new)
        aliases.append({'before_instance': old, 'after_instance': new, 'master': actual[new]['master'],
                        'complete_logical_signature_equal': True})
        for row in candidate[0]:
            if row['name'] == new:
                row['name'] = old
        for row in candidate[1]:
            if row['instance'] == new:
                row['instance'] = old
    result = base.compare_logic(before, candidate, library)
    result['inverter_instance_bijections'] = aliases
    result['delay_identity_proofs'] = delays
    result['transparent_buffer_counts_are_proof_counts_including_delay_aliases'] = True
    result['actual_design_modified'] = False
    return result


def audit_clock_ndr(before, after, bdef, adef, loads, library):
    bp, br = net_properties(bdef)
    ap, ar = net_properties(adef)
    if any(ar.get(name) != definition for name, definition in br.items()):
        raise ValueError('An existing NDR definition changed or disappeared')
    for net, (_, ndr) in bp.items():
        if ndr and ap.get(net) != bp[net]:
            raise ValueError('An existing clock NDR assignment changed')
    unknown = {net: ndr for net, (use, ndr) in ap.items() if ndr and (ndr not in ar or use != 'CLOCK')}
    if unknown:
        raise ValueError('Undefined NDR or NDR assigned to a non-CLOCK net: ' + repr(unknown))
    definitions = {}
    for name, body in ar.items():
        layers = re.findall(r'\+ LAYER (\S+) WIDTH (\d+) SPACING (\d+)', body)
        remainder = re.sub(r'\+ LAYER \S+ WIDTH \d+ SPACING \d+', '', body).strip()
        if remainder or not layers or len({x[0] for x in layers}) != len(layers) or any(int(w) <= 0 or int(s) <= 0 for _, w, s in layers):
            raise ValueError('Unsupported or invalid NDR layer definition')
        definitions[name] = [{'layer': layer, 'width_dbu': int(w), 'spacing_dbu': int(s)} for layer, w, s in layers]
    before_names = {row['name'] for row in before[0]}
    cells = {row['name']: row for row in after[0]}
    load_names = {row['instance'] for row in loads}
    terms = base.unique(after[1], ('instance', 'pin'))
    _, nets, _ = base.parse_def(adef)
    new_buffers = {name for name, row in cells.items() if name not in before_names and name not in load_names and base.cell_kind(row['master'], library) == 'buffer'}
    internal, leaves, exceptions = [], [], []
    for name in sorted(new_buffers):
        source, target = terms[name, 'A']['net'], terms[name, 'X']['net']
        if ap.get(target, (None,))[0] != 'CLOCK':
            continue  # e.g. a data hold-fix buffer; not a CTS branch.
        record = {'driver': name, 'net': target, 'ndr': ap[target][1], 'input_net': source}
        next_buffers = [inst for inst, pin in nets.get(target, set()) if inst in new_buffers and pin == 'A' and ap.get(terms[inst, 'X']['net'], (None,))[0] == 'CLOCK']
        if next_buffers:
            record['downstream_clock_buffers'] = sorted(next_buffers)
            internal.append(record)
            if not record['ndr']:
                exceptions.append(record)
        else:
            leaves.append(record)
    return {'result': 'PASS', 'existing_ndr_definitions_preserved': True,
            'before_ndr_definition_count': len(br), 'after_ndr_definition_count': len(ar), 'definitions': definitions,
            'clock_net_count': sum(use == 'CLOCK' for use, _ in ap.values()),
            'clock_nets_with_ndr': sum(use == 'CLOCK' and ndr is not None for use, ndr in ap.values()),
            'internal_clock_buffer_branches': internal, 'leaf_clock_buffer_branches': leaves,
            'internal_clock_branches_without_ndr': exceptions,
            'all_internal_clock_branches_have_ndr': not exceptions,
            'routing_ndr_policy_qualification': 'UNVERIFIED',
            'leaf_clock_branches_without_ndr': sum(row['ndr'] is None for row in leaves),
            'scope': 'actual DEF CLOCK labels, existing NDR preservation, defined NDR references and explicit branch coverage; no unprovided all-trunk NDR policy is assumed',
            'routing_rule_legality_or_waveform_timing_proven': False}


def audit(root, run_id, base_report):
    report_path = root / base_report
    prior = json.loads(report_path.read_text())
    if prior['run_id'] != run_id or prior['physical_invariants']['result'] != 'PASS' or any(prior['def_export_crosschecks'][phase]['result'] != 'PASS' for phase in ('before', 'after')):
        raise ValueError('Require completed physical and DEF/export crosschecks for this run')
    hashes = dict(prior['source_sha256'])
    hashes[base_report] = base.sha(report_path)
    hashes['scripts/audit_croc_cts_structure.py'] = base.sha(root / 'scripts/audit_croc_cts_structure.py')
    for rel, digest in hashes.items():
        if base.sha(root / rel) != digest:
            raise ValueError('Evidence hash changed: ' + rel)
    run = root / 'runs' / run_id
    snapshots = {}
    for phase in ('before', 'after'):
        snapshots[phase] = []
        for kind in ('instances', 'iterms', 'bterms'):
            with (run / (phase + '_' + kind + '.tsv')).open() as handle:
                snapshots[phase].append(list(csv.DictReader(handle, delimiter='\t')))
    library = base.liberty_logic((root / 'upstream/croc/technology/lib/sg13g2_stdcell_typ_1p20V_25C.lib').read_text())
    bdef, adef = ((run / (phase + '.def')).read_text() for phase in ('before', 'after'))
    filtered, loads = abstract_unobserved_loads(snapshots['before'], snapshots['after'], library, adef)
    result = {'run_id': run_id, 'classification': 'CTS_unobserved_load_abstraction_and_clock_metadata_not_formal_or_signoff',
              'source_sha256': hashes, 'generic_conservative_audit_result': prior['overall_result'],
              'physical_invariants': prior['physical_invariants'], 'abstracted_load_count': len(loads),
              'abstracted_loads_by_master': dict(Counter(row['master'] for row in loads)),
              'actual_before_instances': len(snapshots['before'][0]),
              'actual_after_instances': len(snapshots['after'][0]),
              'unobserved_clock_loads': loads,
              'full_formal_equivalence_proven': False, 'electrical_or_signoff_proven': False,
              'actual_load_cells_removed_from_checkpoint': False}
    for key, action in [('normalized_connectivity', lambda: prove_cts_logic(snapshots['before'], filtered, library)),
                        ('clock_ndr', lambda: audit_clock_ndr(snapshots['before'], snapshots['after'], bdef, adef, loads, library))]:
        try:
            result[key] = action()
        except ValueError as error:
            result[key] = {'result': 'UNVERIFIED', 'reason': str(error)}
    result['overall_result'] = 'PASS' if all(result[key]['result'] == 'PASS' for key in ('normalized_connectivity', 'clock_ndr')) else 'UNVERIFIED'
    result['limitations'] = ['Only stateless added cells whose output is not observed are abstracted for 2-state connectivity; their real electrical/physical effects are retained in the actual design.',
                             'This report does not waive DRC/LVS, capacitance/slew, IR/EM, clock waveform or extracted MMMC timing.']
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--base-report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = root / args.output
    if path.exists(): raise ValueError('Preserve previous report; use an independent output')
    result = audit(root, args.run_id, args.base_report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('run_id', 'overall_result', 'abstracted_load_count', 'abstracted_loads_by_master')}, indent=2))
    raise SystemExit(0 if result['overall_result'] == 'PASS' else 1)
