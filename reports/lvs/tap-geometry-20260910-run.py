#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute the single authorized bounded geometry readback, create-only."""
import importlib.util
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('runner',ROOT/'reports/lvs/run_tap_reader_ab.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)

def main():
    run=ROOT/'runs/tap-geometry-20260910-001';run.mkdir()
    script=ROOT/'reports/lvs/tap-geometry-20260910-probe.py'
    shutil.copyfile(script,run/script.name)
    shutil.copyfile(Path(__file__),run/Path(__file__).name)
    sources=[script,Path(__file__),ROOT/'reports/lvs/run_tap_reader_ab.py',
             ROOT/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001/control/inputs/sg13g2_DCNDiode.gds']
    deck=ROOT/'upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks'
    sources += [deck/f for f in ('tap_derivations.lvs','tap_extraction.lvs','tap_connections.lvs','general_derivations.lvs',
                                'layers_definitions.lvs','custom_classes.lvs','custom_devices.lvs','custom_combiner.lvs','custom_reader.lvs','rfmos_model_mapping.lvs')]
    manifest={'run_id':run.name,'classification':'single_read_only_DCN_geometry_probe_no_LVS',
              'source_sha256':MOD.hashes(sources),'source_pdk_modified':False,'lvs_performed':False}
    MOD.save(run/'manifest.json',manifest)
    manifest['execution']=MOD.run_container(run,run.name,['python3','/output/'+script.name])
    manifest['source_hashes_unchanged']=all(MOD.sha(ROOT/p)==h for p,h in manifest['source_sha256'].items())
    manifest['output_sha256']={str(p.relative_to(run)):MOD.sha(p) for p in MOD.all_files(run) if p.name!='manifest.json'}
    MOD.save(run/'manifest.json',manifest)
    MOD.require_terminal(manifest['execution'])
    print(json.dumps({'run':run.name,'source_hashes_unchanged':manifest['source_hashes_unchanged']}))

if __name__=='__main__':main()
