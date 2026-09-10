#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read only the two bounded DCN LVS databases; perform no new extraction."""
import importlib.util
import json
from pathlib import Path

ROOT=Path('/work')
SPEC=importlib.util.spec_from_file_location('xref',ROOT/'scripts/analyze_small_lvsdb.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)
for arm in ('control','candidate'):
    path=ROOT/'runs/croc-lvs-tap-reader-dcn-ab-20260910-001'/arm/'result/sg13g2_DCNDiode.lvsdb'
    size=MOD.enforce_size_limit(path,8*1024*1024)
    result=MOD.analyze(path,50)
    result.update(source_sha256=MOD.sha256_file(path),source_bytes=size,read_only=True)
    (Path('/output')/(arm+'.json')).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(arm,json.dumps(result['summary']))
