#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build one real input IO and matched bondpad inside the complete original seal."""
import argparse, json
from pathlib import Path
import klayout.db as k
from build_bondpad_io_fixture import LAYERS, region, sha


def make(root, output):
    output.mkdir(parents=True, exist_ok=True)
    archive = root/'runs/croc-sg13g2-baseline-20260827-001/artifacts/gds.attempt-4/upstream/croc/klayout/out/croc.filled.gds.gz'
    bond_source = root/'runs/croc-bondpad-io-ab-20260905-001/inputs/bondpad70_m2_ring.gds'
    io_source = root/'upstream/croc/technology/gds/sg13g2_io.gds'
    old_facts = root/'runs/croc-bondpad-io-ab-20260905-001/inputs/fixture_summary.json'
    assert sha(bond_source) == json.loads(old_facts.read_text())['lef_gds_contract']['gds_sha256']
    sealed = k.Layout(); sealed.read(str(archive))
    assert sealed.dbu == 0.001
    seal_instances = [i for i in sealed.top_cell().each_inst() if i.cell.name == 'sealring_top']
    assert len(seal_instances) == 1
    seal_inst = seal_instances[0]
    assert seal_inst.cplx_trans == k.ICplxTrans()
    assert seal_inst.cell.bbox() == k.Box(0, 0, 2000000, 2000000)
    seal_source = output/'sealring_from_baseline.gds'
    assert not seal_source.exists()
    seal_inst.cell.write(str(seal_source))
    summary = {'classification': 'single_io_complete_seal_fixture_not_chip_signoff',
        'source_sha256': {str(p.relative_to(root)): sha(p) for p in (archive, bond_source, io_source, old_facts)},
        'full_chip_modified': False, 'all_other_chip_instances_and_fill_excluded': True,
        'seal_subtree_preserved': True, 'seal_gds_sha256': sha(seal_source),
        'canonical_transform_from_sealed_dbu': 'm45 -560000,-112000',
        'lvs_performed': False, 'arms': []}
    # Control already has the proven 4um external lead. Candidate adds seal margin.
    for name, pad_shift, io_shift in [('official_seal_control', 0, 4000),
                                      ('official_seal_margined', 17400, 21500)]:
        l = k.Layout(); l.read(str(bond_source)); bond = l.cell('bondpad70_m2_ring')
        l.read(str(io_source)); io = l.cell('sg13g2_IOPadIn')
        l.read(str(seal_source)); seal = l.cell('sealring_top')
        assert bond is not None and io is not None and seal is not None
        top = l.create_cell(name)
        normal = k.Trans(k.Trans.M45, -560000, -112000)
        top.insert(k.CellInstArray(seal.cell_index(), normal))
        top.insert(k.CellInstArray(io.cell_index(), k.Trans(0, io_shift)))
        bond_trans = k.Trans(5000, -70000 + pad_shift)
        top.insert(k.CellInstArray(bond.cell_index(), bond_trans))
        per_layer = {}
        pin = k.Region(k.Box(5000, io_shift, 75000, io_shift + 3000))
        lead = k.Region(k.Box(5000, pad_shift, 75000, io_shift))
        for layer, pair in LAYERS.items():
            existing = region(l, io, pair).transformed(k.Trans(0, io_shift))
            pad_metal = region(l, bond, pair).transformed(bond_trans)
            assert (pin - existing).is_empty()
            assert (lead & existing).is_empty()
            assert (pad_metal | lead | pin).merged().count() == 1
            top.shapes(l.layer(*pair)).insert(lead)
            per_layer[layer] = {'pad_lead_io_connected': True, 'added_lead_area_um2': lead.area()*l.dbu**2}
        opening = region(l, bond, (9,0)).transformed(bond_trans) & region(l, bond, (41,0)).transformed(bond_trans)
        active = region(l, io, (1,0)).transformed(k.Trans(0, io_shift))
        seal_active = (region(l, seal, (1,0)) & region(l, seal, (39,0))).transformed(normal)
        item = {'name': name, 'topcell': name, 'bbox_um': str(top.dbbox()),
            'pad_inward_shift_um': pad_shift/1000, 'io_inward_shift_um': io_shift/1000,
            'gap_um': (io_shift-pad_shift)/1000, 'seal_shift_um': 0,
            'opening_active_separation_11p2um_pairs': opening.separation_check(active, 11200).count(),
            'opening_seal_active_separation_25um_pairs': opening.separation_check(seal_active, 25000).count(),
            'per_layer': per_layer, 'neighbor_io_fill_pg_included': False,
            'complete_netlist_equivalence_proven': False}
        dest = output/(name+'.gds'); assert not dest.exists(); top.write(str(dest))
        item['gds_sha256'] = sha(dest); summary['arms'].append(item)
    summary['outputs_sha256'] = {p.name: sha(p) for p in output.glob('*.gds')}
    with (output/'fixture_summary.json').open('x') as f:
        json.dump(summary, f, indent=2, sort_keys=True); f.write('\n')
    print(json.dumps({'arms': [{k: a[k] for k in ('name','gap_um','opening_active_separation_11p2um_pairs','opening_seal_active_separation_25um_pairs')} for a in summary['arms']]}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/work'))
    p.add_argument('--output', type=Path, default=Path('/output'))
    a = p.parse_args(); make(a.root, a.output)
