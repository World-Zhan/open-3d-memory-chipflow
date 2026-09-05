#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded read-only Croc bondpad comparison; only writes independent output artifacts."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import klayout.db as k

parser = argparse.ArgumentParser()
parser.add_argument("--root", default="/work", type=Path)
parser.add_argument("--output-dir", default="/output", type=Path)
parser.add_argument("--include-chip", action="store_true")
args = parser.parse_args()
root, output = args.root, args.output_dir
output.mkdir(parents=True, exist_ok=True)
pdk = root / "upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout"
source_macro = root / "upstream/croc/technology/gds/bondpad_70x70.gds"
source_lef = root / "upstream/croc/technology/lef/bondpad_70x70.lef"
source_chip = root / "runs/croc-sg13g2-baseline-20260827-001/artifacts/gds.attempt-4/upstream/croc/klayout/out/croc.filled.gds.gz"
drc_db = root / "runs/croc-sg13g2-baseline-20260827-001/signoff.attempt-2/drc/croc.filled.gds_croc_chip_sealed_full.lyrdb"
tech_path = pdk / "python/sg13g2_pycell_lib/sg13g2_tech.json"
tech = json.loads(tech_path.read_text())
layer_map = {key: tuple(map(int, value.split(","))) for key, value in tech["Layers"].items()}
for entry in ET.parse(pdk / "tech/sg13g2.lyp").findall(".//properties"):
    name, source = entry.findtext("name"), entry.findtext("source")
    if name and source:
        layer_map[name] = tuple(map(int, source.split("/")))
names = ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5", "TopMetal1", "TopMetal2", "TopVia1", "TopVia2", "Passiv", "dfpad", "Activ", "EdgeSeal"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def layer_pair(name):
    return layer_map.get(name + ".drawing", layer_map.get(name))


def region(layout, cell, name):
    pair = layer_pair(name)
    if pair is None:
        return k.Region()
    index = layout.find_layer(*pair)
    return k.Region(cell.begin_shapes_rec(index)) if index is not None else k.Region()


def summary(layout, cell):
    result = {"cell": cell.name, "dbu_um": layout.dbu, "bbox_um": str(cell.dbbox()), "layers": {}}
    for name in names:
        r = region(layout, cell, name)
        result["layers"][name] = {"gds_pair": layer_pair(name), "polygon_count": r.count(),
                                  "merged_area_um2": r.merged().area() * layout.dbu ** 2,
                                  "bbox_um": str(r.bbox().to_dtype(layout.dbu))}
    tv2, opening = region(layout, cell, "TopVia2"), region(layout, cell, "Passiv") & region(layout, cell, "dfpad")
    result["topvia2_fully_inside_pad_opening"] = tv2.inside(opening).count()
    result["topvia2_intersecting_pad_opening"] = tv2.interacting(opening).count()
    result["topvia2_overlap_opening_area_um2"] = (tv2 & opening).area() * layout.dbu ** 2
    return result


sources = [source_macro, source_lef, tech_path, pdk / "python/sg13g2_pycell_lib/ihp/bondpad_code.py", pdk / "tech/sg13g2.lyp", drc_db]
payload = {"schema_version": "1.0.0", "classification": "geometry_diagnostic_not_signoff", "klayout_version": k.__version__,
           "source_sha256": {str(path.relative_to(root)): digest(path) for path in sources},
           "layer_map": {name: layer_pair(name) for name in names}}
layout = k.Layout()
layout.read(str(source_macro))
cell = layout.top_cell()
payload["croc_macro"] = summary(layout, cell)

# Load the fixed checked-out PCell/CNI sources, not the image's bundled PDK.
os.environ["KLAYOUT"] = "1"
os.environ["KLAYOUT_LYP_FILE"] = str(pdk / "tech/sg13g2.lyp")
for path in (pdk / "python", pdk / "python/pycell4klayout-api/source/python"):
    sys.path.insert(0, str(path))
import sg13g2_pycell_lib  # noqa: E402,F401
import pya  # noqa: E402

lib = pya.Library.library_by_name("SG13_dev", "sg13g2")
if lib is None:
    raise RuntimeError("fixed official SG13_dev library did not register")
decl = lib.layout().pcell_declaration("bondpad")
payload["official_pcell_parameters"] = {p.name: p.default for p in decl.get_parameters()}
payload["official_variants"] = {}
for name, params in {
    "official_default_square70": {"diameter": "70u", "shape": "square"},
    "official_m2_square70": {"diameter": "70u", "shape": "square", "bottomMetal": "2", "stack": "t", "fill": "nil", "FlipChip": "no", "padType": "bondpad"},
}.items():
    generated = k.Layout(True)
    generated.dbu = 0.001
    top = generated.create_cell(name)
    index = generated.add_pcell_variant(lib, decl.id(), params)
    top.insert(k.CellInstArray(index, k.Trans()))
    item = summary(generated, top)
    item["explicit_parameters"] = params
    path = output / (name + ".gds")
    if path.exists():
        raise FileExistsError("Use a new diagnostic output directory: " + str(path))
    generated.write(str(path))
    item["generated_gds_sha256"] = digest(path)
    payload["official_variants"][name] = item

tree = ET.parse(drc_db)
counts = Counter(item.findtext("category") for item in tree.findall(".//items/item"))
payload["archived_drc_category_counts"] = dict(sorted(counts.items()))

if args.include_chip:
    chip = k.Layout()
    chip.read(str(source_chip))
    top = chip.top_cell()
    payload["source_sha256"][str(source_chip.relative_to(root))] = digest(source_chip)
    # Read only layer geometry and source-cell attribution; no DRC engine invoked.
    payload["chip"] = {"top_cell": top.name, "dbu_um": chip.dbu, "bbox_um": str(top.dbbox())}
    opening = region(chip, top, "Passiv") & region(chip, top, "dfpad")
    via_index = chip.find_layer(*layer_pair("TopVia2"))
    iterator = top.begin_shapes_rec(via_index)
    total, under_opening = Counter(), Counter()
    samples = []
    while not iterator.at_end():
        shape = iterator.shape()
        if shape.is_box() or shape.is_polygon() or shape.is_path():
            polygon = shape.polygon.transformed(iterator.trans())
            source = iterator.cell().name
            total[source] += 1
            if not k.Region(polygon).inside(opening).is_empty():
                under_opening[source] += 1
                if len(samples) < 12:
                    samples.append({"source_cell": source, "bbox_um": str(polygon.bbox().to_dtype(chip.dbu))})
        iterator.next()
    payload["chip"]["topvia2_count_by_source_cell"] = dict(total)
    payload["chip"]["topvia2_fully_inside_pad_opening_by_source_cell"] = dict(under_opening)
    payload["chip"]["topvia2_inside_opening_samples"] = samples

payload["limitations"] = ["Geometry and archived-marker review only; no full-chip DRC/LVS executed.",
                           "Generated PCell variants are isolated fixture artifacts, not substituted into Croc.",
                           "No signoff, bonding/packaging acceptance, or repaired-route claim is made."]
with (output / "geometry_summary.json").open("x") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
print("BOND_GEOMETRY_DIAGNOSTIC_COMPLETED", flush=True)
