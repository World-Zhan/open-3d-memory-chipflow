# [Draft] SG13G2 IO diode leaves do not strict-deep LVS-match the official schematics

Status: **local upstream issue draft; not published**. This document records a
minimal reproducer for discussion with the IHP Open PDK maintainers. It does
not authorize a GitHub issue, repository publication, deck change, waiver, or
full-chip signoff attempt.

## Summary

At IHP Open PDK commit
`331c00484213b13414777eec1336ef5c29b969bd`, the official
`sg13g2_DCNDiode` and `sg13g2_DCPDiode` GDS leaves both fail strict-deep
KLayout LVS against subcircuits copied verbatim from the official CDL. The
official SPICE view agrees with the CDL that both antenna devices share one
`cathode` net in DCN and one `anode` net in DCP.

Observed extraction:

| Cell | Schematic ports | Extracted ports | Structural result |
|---|---|---|---|
| `sg13g2_DCNDiode` | `anode cathode guard` | `anode cathode cathode$1` | FAIL; `guard` missing, `cathode$1` extra |
| `sg13g2_DCPDiode` | `anode cathode guard` | `guard cathode anode anode$1` | FAIL; `anode$1` extra |

Both KLayout cross-references classify the leaf circuit as `NoMatch`.
Devices and nets are layout-only versus schematic-only, so this is not a
paired parameter-tolerance failure.

## Environment and immutable inputs

- Container: `hpretl/iic-osic-tools:2025.12`
- Container digest: `sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521`
- IHP Open PDK commit: `331c00484213b13414777eec1336ef5c29b969bd`
- IO GDS SHA-256: `4281a855377b6a1ca46356e9391258dc14e8efc3b8051a65befc0fe9db3c7825`
- IO CDL SHA-256: `7a30e902099e8a8f85e0ae853167904df3793357a793a7b4dc82237b72b3eec4`
- IO SPICE SHA-256: `1d53ab7df431b717ef5aff43e1117c0224681d5cc84886da37a319280ee958d6`
- `run_lvs.py` SHA-256: `1079e9ac83f5b1b97a2c77c11143783556a391780772126ac3e5c5c300210ef3`
- `layers_definitions.lvs` SHA-256: `2165a344d178eff60c2c79ad73108d74b8a1d2b1a5183e8b3492aa249887e58c`
- `general_connections.lvs` SHA-256: `bb61656b3564cf08558b83cf27d09854049eb30b5b7ade6610045d43c4b53e97`

The run keeps `run_mode=deep`, strict ports, `flag_missing_ports=true`, tap
extraction and simplify. It does not use `ignore_top_ports_mismatch`, implicit
nets, `--disable_tap_extraction`, `--no_simplify`, `--layout_netlist`, waivers,
or a modified rule deck.

## Reproduction

Run from the repository root inside WSL ext4:

```sh
docker run --rm -v "$PWD:/work" hpretl/iic-osic-tools:2025.12 --skip \
  python3 /work/scripts/run_lvs_iopad_leaf_diagnostic.py \
  --repo-root /work \
  --run-dir /work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001
```

The recorded strict-deep runner commands are:

```text
/usr/bin/python3 /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs/run_lvs.py --layout=/work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/sg13g2_DCNDiode/inputs/sg13g2_DCNDiode.gds --netlist=/work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/sg13g2_DCNDiode/inputs/sg13g2_DCNDiode.cdl --run_dir=/work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/sg13g2_DCNDiode --topcell=sg13g2_DCNDiode --run_mode=deep
/usr/bin/python3 /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs/run_lvs.py --layout=/work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/sg13g2_DCPDiode/inputs/sg13g2_DCPDiode.gds --netlist=/work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/sg13g2_DCPDiode/inputs/sg13g2_DCPDiode.cdl --run_dir=/work/runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/sg13g2_DCPDiode --topcell=sg13g2_DCPDiode --run_mode=deep
```

Generated minimal-input hashes:

| Cell | Minimal GDS | Minimal CDL |
|---|---|---|
| DCN | `aa14969a06a07d45e27316cfbccc46a262b943842474a85f26159da6841ea81f` (114,798 B) | `e6beb7b9b6eb3ac828ae597aebb68e8773ee5c0408ab3f0ca1867f652d930e43` (349 B) |
| DCP | `ca9ff63fc89df9056fd19dd3efd93add6d2fa79fa813072c6fe7bf49e42e5f4f` (114,836 B) | `4179ad18e54dd2b5a94bd019d2f38665d66ee690a0c0d7d7945e9a65d7026708` (352 B) |

The generated minimal-GDS raw SHA-256 values above identify the retained
2026-08-29 files only. They are **not** a bitwise-determinism contract:
KLayout refreshes GDSII `BGNLIB`/`BGNSTR` timestamps when exporting an
equivalent selected cell. Stable input identity is instead the pinned IHP PDK
commit, the official source IO-GDS SHA-256, the source cell name, and the
recorded DBU/bounding-box/direct-shape facts in `summary.json`. The generated
CDL is text and retained a stable raw SHA-256 across reruns. No semantic
geometry digest is claimed.

A two-leaf-only reverification on 2026-08-30 is retained at
`runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260830-rerun-002/`.
It reproduced the same port splits and cross-reference counts. The deck
reported valid runtimes of 1.766733 s for DCN and 1.674267 s for DCP; the whole
container invocation took 16.21 s wall clock. An earlier rerun made the deck
emit `LVS Total Run time -1.431181 seconds` for DCP. That negative value is
preserved as raw log evidence but normalized to `deck_runtime_seconds=null`,
`deck_runtime_valid=false`; it is not reported as elapsed time.

## Cross-reference evidence

| Cell | circuit | devices | nets | pins | Small LVSDB |
|---|---|---|---|---|---|
| DCN | `NoMatch=1` | layout-only 3; schematic-only 1 | layout-only 4; schematic-only 2 | Match 4 | 54,778 B; `d47e30b72e521e2c416bd250d8317929bd75ff2ed337584d6276b3589db9b07d` |
| DCP | `NoMatch=1` | layout-only 3; schematic-only 1 | layout-only 5; schematic-only 2 | Match 6 | 64,085 B; `a9b5782f3d1673a48b82c60b9e2d49254957ebc1be2f04f8f92e18513b38a98f` |

The two small `.lvsdb` files, extracted netlists, logs and bounded JSON
cross-references remain local under
`runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-leaf-diagnostic-20260829-001/`.
They are intentionally ignored by Git.

## Official parent-geometry check

A bounded read-only geometry audit checked the two direct leaf instances under
the official `sg13g2_IOPadIn` parent. M1 conductor follows the public deck:
drawing/fill `8/0 + 8/22`, text `8/25`.

- DCN duplicated `cathode` access components touch parent M1 components 1 and
  0 respectively; their shared-parent-component set is empty.
- DCP duplicated `anode` access components touch parent M1 components 7 and 6
  respectively; their shared-parent-component set is empty.
- Therefore no direct parent M1 closure is present in this official parent
  cell, and a speculative bridge was not drawn or tested.

Evidence:
`runs/croc-sg13g2-baseline-20260827-001/lvs-iopad-parent-metal-closure-20260829-001/official_parent_connectivity.json`
(5,952 B, SHA-256
`9c183265fb2070d58380ae378001c0281580f671cb26fda361721e67203846de`).

## Separate full-chip symptom

This leaf blocker coexists with a separate full-chip flat-extraction boundary
failure: the Croc schematic has 52 top formal ports, while the extracted
`croc_chip` has 135,057 formal ports and zero exact-name shared ports. Flat
child-label promotion accounts for that first full-chip comparison boundary.
The two strict-deep leaf failures do **not** explain all 135,057 ports, and the
full-chip mismatch must not be attributed to IO alone.

## Expected behavior and upstream questions

The official IO GDS leaf should strict-match the official CDL/SPICE view using
the public deck, or the PDK should document the supported hierarchy/abstract
flow and provide a matching regression. Please clarify:

1. Are the two access regions intended to be connected in the leaf or by a
   documented parent construct not present in `sg13g2_IOPadIn` direct M1?
2. Is there known version skew between IO GDS, CDL/SPICE and the public KLayout
   LVS deck at this commit?
3. Is there an official DCN/DCP strict-LVS regression or a supported IO-leaf
   abstraction mechanism? None was found in the public runner/documentation.

Until an upstream-supported resolution exists, the project will not change
the deck, hide guard/substrate devices, add implicit nets, or start Croc
full-chip attempt 3.
