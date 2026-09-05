#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that collapsing new non-inverting clock buffers restores connectivity."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def section(text, name):
    match = re.search(r"^\s*" + name + r"\s+(\d+)\s*;(.*?)^\s*END " + name + r"\s*$", text, re.M | re.S)
    if not match:
        raise ValueError(f"Missing {name} section")
    records = re.findall(r"^\s*-\s+(\S+)\s+(.*?);", match[2], re.M | re.S)
    if len(records) != int(match[1]):
        raise ValueError(f"Incomplete {name} parse")
    if len({record_name for record_name, _ in records}) != len(records):
        raise ValueError(f'Duplicate {name} record names')
    return records


def parse_def(text):
    cells = {name: body.split()[0] for name, body in section(text, 'COMPONENTS')}
    nets = {}
    for name, body in section(text, 'NETS') + section(text, 'SPECIALNETS'):
        connection_text = body.split('+', 1)[0]
        # Preserve DEF wildcard PG connections literally; never expand them
        # without master-pin information. New buffer supplies still need
        # explicit instance/pin connections below.
        pins = set(re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", connection_text))
        if re.sub(r"\(\s*\S+\s+\S+\s*\)", '', connection_text).strip():
            raise ValueError('Unsupported DEF connection syntax')
        if any(inst not in cells and inst not in ('PIN', '*') for inst, _ in pins):
            raise ValueError('Unknown instance in DEF net connectivity')
        nets.setdefault(name, set()).update(pins)
    die = re.search(r"^\s*DIEAREA\s+(.+?);", text, re.M)
    units = re.search(r"^\s*UNITS DISTANCE MICRONS\s+(\d+)\s*;", text, re.M)
    if not die or not units:
        raise ValueError('Missing die/units')
    return cells, nets, (units[1], ' '.join(die[1].split()))


def clock_properties(text):
    properties = {}
    for name, body in section(text, 'NETS'):
        use = re.search(r"\+ USE\s+(\S+)", body)
        ndr = re.search(r"\+ NONDEFAULTRULE\s+(\S+)", body)
        properties[name] = (use[1] if use else None, ndr[1] if ndr else None)
    rules = {name: ' '.join(body.split()) for name, body in section(text, 'NONDEFAULTRULES')}
    return properties, rules


def validate(before_text, after_text):
    before_cells, before_nets, before_die = parse_def(before_text)
    after_cells, after_nets, after_die = parse_def(after_text)
    added = set(after_cells) - set(before_cells)
    expected = {f'eco_cts_b{branch}_g{group}' for branch in range(4) for group in range(2)}
    if added != expected or any(after_cells.get(name) != master for name, master in before_cells.items()):
        raise ValueError('Only eight specified buffers may be added; original masters must match')
    if any(after_cells[name] != 'sg13g2_buf_8' for name in added):
        raise ValueError('New instances must be non-inverting sg13g2_buf_8')
    if before_die != after_die:
        raise ValueError('Die boundary or units changed')
    pin_to_net = {}
    for net, pins in after_nets.items():
        for pin in pins:
            if pin[0] == '*':
                continue  # symbolic PG declaration, not a unique instance pin
            if pin in pin_to_net and pin_to_net[pin] != net:
                raise ValueError('Pin appears on multiple nets')
            pin_to_net[pin] = net
    before_properties, before_rules = clock_properties(before_text)
    after_properties, after_rules = clock_properties(after_text)
    if before_rules != after_rules:
        raise ValueError('Original clock NDR definitions changed')
    if any(after_properties.get(n) != props for n, props in before_properties.items()):
        raise ValueError('Original net use or NDR changed')
    inherited_rules = {}
    aliases = {}
    for name in sorted(added):
        src = pin_to_net.get((name, 'A'))
        dst = pin_to_net.get((name, 'X'))
        if not src or not dst or src == dst or dst in before_nets:
            raise ValueError('Buffer must bridge original source and new destination net')
        if len(after_nets[dst] - {(name, 'X')}) != 8:
            raise ValueError('Each new branch must have exactly eight loads')
        if pin_to_net.get((name, 'VDD')) != 'VDD' or pin_to_net.get((name, 'VSS')) != 'VSS':
            raise ValueError('Explicit VDD/VSS buffer supply connection required')
        source_properties = before_properties.get(src)
        if not source_properties or source_properties[0] != 'CLOCK' or source_properties[1] not in before_rules:
            raise ValueError('Source must be an original CLOCK net with a defined NDR')
        if after_properties.get(dst) != source_properties:
            raise ValueError('New clock net must inherit source CLOCK use and NDR')
        inherited_rules[dst] = source_properties[1]
        aliases[dst] = src
    collapsed = {}
    for net, pins in after_nets.items():
        target = aliases.get(net, net)
        collapsed.setdefault(target, set()).update(pin for pin in pins if pin[0] not in added)
    if collapsed != before_nets:
        differing = sorted(set(collapsed) ^ set(before_nets) | {n for n in before_nets if collapsed.get(n) != before_nets[n]})
        raise ValueError(f'Connectivity changed after buffer collapse: {differing[:8]}')
    return {'structural_connectivity_after_buffer_collapse':'passed', 'added_buffers':len(added),
            'loads_per_new_branch':8, 'buffer_cell':'sg13g2_buf_8', 'die_boundary_preserved':True,
            'explicit_buffer_supplies_connected':True,
            'clock_ndr_inheritance':inherited_rules, 'original_ndr_definitions_preserved':True, 'full_formal_equivalence_proven':False,
            'clock_waveform_timing_proven':False, 'route_or_signoff_proven':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=validate(args.before.read_text(),args.after.read_text())
    data['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.before,args.after)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:
        json.dump(data,f,indent=2); f.write('\n')
    print(json.dumps(data))


if __name__=='__main__':
    main()
