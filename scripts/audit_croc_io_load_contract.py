#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit IO load/model compatibility and classify actual electrical violations; no EDA."""
import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from audit_croc_placement_structure import groups, attribute

NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'

def positive(value):
    result=float(value)
    if not math.isfinite(result) or result<=0:
        raise ValueError('Expected finite positive library value')
    return result

def digital_io_limits(text):
    units=re.findall(r'capacitive_load_unit\s*\(\s*('+NUMBER+r')\s*,\s*(\w+)\s*\)',text)
    if len(units)!=1 or units[0][1].lower()!='pf' or positive(units[0][0])!=1:
        raise ValueError('Require explicit 1 pF library units')
    limits={}
    for name,body in groups(text,'cell'):
        if not re.fullmatch(r'sg13g2_IOPad(?:InOut|Out|TriOut)(?:4|16|30)mA',name):continue
        pads=[payload for pin,payload in groups(body,'pin',direct=True) if pin=='pad']
        if name in limits or len(pads)!=1:raise ValueError('Missing/duplicated digital pad')
        if attribute(pads[0],'direction') not in ('output','inout'):raise ValueError('Expected driven pad')
        cap=attribute(pads[0],'max_capacitance')
        if cap is None:raise ValueError('Missing explicit max capacitance')
        limits[name]=positive(cap)
    if not limits:raise ValueError('No supported digital IO models')
    return limits

def classify_violations(text):
    result={}
    for title in ('max slew','max fanout','max capacitance'):
        found=re.findall(r'^'+re.escape(title)+r'\s*\n(.*?)(?=^max (?:slew|fanout|capacitance)\s*$|\Z)',text,re.M|re.S)
        if len(found)!=1:raise ValueError('Missing/duplicate report section: '+title)
        rows=[]
        for line in found[0].splitlines():
            if 'VIOLATED' not in line:continue
            match=re.fullmatch(r'\s*(\S+)\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+\(VIOLATED\)\s*',line)
            if not match:raise ValueError('Malformed violated row')
            pin=match[1]
            category=('external_gpio_driver' if re.fullmatch(r'gpio\d+_io',pin) else
                      'chip_io_pad' if re.fullmatch(r'pad_\S+/pad',pin) else
                      'sram_output' if re.search(r'/A_DOUT\[\d+\]$',pin) else
                      'clock_buffer' if re.fullmatch(r'clkbuf_\S+/X',pin) else 'unclassified')
            limit,actual,slack=map(float,match.groups()[1:])
            if not all(math.isfinite(v) for v in (limit,actual,slack)) or limit<=0 or actual<=limit or slack>=0:
                raise ValueError('Inconsistent violation values')
            rows.append({'pin':pin,'category':category,'limit':limit,'actual':actual,'slack':slack})
        result[title]={'count':len(rows),'by_category':dict(Counter(row['category'] for row in rows)),'rows':rows}
    return result

def audit(root):
    run=root/'runs/croc-full-io-cts-20260909-001'
    manifest=json.loads((run/'manifest.json').read_text())
    if manifest['status']!='completed' or manifest['returncode']!=0:raise ValueError('Unfinished source')
    hashes={}
    def read(path,expected=None):
        data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if expected is not None and digest!=expected:raise ValueError('Changed source '+str(path))
        hashes[str(path.relative_to(root))]=digest
        return data.decode()
    read(run/'manifest.json')
    read(root/'scripts/audit_croc_io_load_contract.py')
    read(root/'scripts/audit_croc_placement_structure.py')
    sdc=read(run/'after.sdc',manifest['outputs_sha256']['after.sdc'])
    loads=re.findall(r'^set_load\s+-pin_load\s+('+NUMBER+r')\s+\[get_ports\s+\{([^{}]+)\}\]',sdc,re.M)
    if not loads:
        loads=re.findall(r'^set_load\s+('+NUMBER+r')\s+\[get_ports\s+\{([^{}]+)\}\]',sdc,re.M)
    required={port:positive(value) for value,port in loads if re.fullmatch(r'(?:gpio\d+_io|status_o|uart_tx_o|jtag_tdo_o|unused\d+_o)',port)}
    if len(required)!=39 or set(required.values())!={15.0}:raise ValueError('Changed/missing 39 digital output loads')
    libraries={}
    for corner,filename in [('tt','sg13g2_io_typ_1p2V_3p3V_25C.lib'),('ff','sg13g2_io_fast_1p32V_3p6V_m40C.lib')]:
        path=root/'upstream/croc/technology/lib'/filename
        text=read(path,manifest['source_sha256'][str(path.relative_to(root))])
        caps=digital_io_limits(text)
        if len(caps)!=9:raise ValueError('Changed digital IO catalog')
        libraries[corner]={'max_capacitance_pf':caps,'largest_catalog_limit_pf':max(caps.values()),
                           'all_catalog_limits_below_15pf':all(v<15 for v in caps.values())}
    violations=classify_violations(read(run/'electrical_violators.rpt',manifest['outputs_sha256']['electrical_violators.rpt']))
    constraints=root/'upstream/croc/openroad/src/constraints.sdc'
    read(constraints)
    return {'schema_version':'1.0.0','classification':'static_model_load_contract_not_physical_drive_or_signoff',
      'source_run':run.name,'source_sha256':hashes,'required_output_loads_pf':required,'libraries':libraries,
      'violations':violations,'io_load_pf_unchanged':15,'existing_catalog_drop_in_IO_satisfies_15pf_cap_limit':False,
      'contract_result':'INCOMPATIBLE_WITH_PINNED_DIGITAL_IO_MAX_CAP_LIMITS',
      'scope':'Digital characterized IO macros only; Analog passive pad is not a replacement digital output driver.',
      'source_pdk_modified':False,'layout_modified':False,'electrical_acceptance':'FAIL',
      'next_actions':['Keep 15 pF unless actual product/board requirements establish a different approved contract.',
                      'Seek qualified IO timing models compatible with actual external load; larger existing drive variants alone cannot meet current limits.',
                      'Separate 32 external GPIO driver, 39 chip IO and 64 SRAM output capacitance records; qualify receiver/loading constraints for bidirectional modes.',
                      'Treat SRAM output buffering as a distinct local ECO; it does not fix the IO model/load mismatch.'],
      'public_rule_signoff':False,'foundry_signoff':False}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();root=Path(__file__).resolve().parents[1];report=audit(root)
    with args.output.open('x') as f:json.dump(report,f,indent=2,ensure_ascii=False);f.write('\n')
    print(json.dumps({'contract_result':report['contract_result'],'libraries':report['libraries'],
                     'counts':{k:{'count':v['count'],'by_category':v['by_category']} for k,v in report['violations'].items()}}))
