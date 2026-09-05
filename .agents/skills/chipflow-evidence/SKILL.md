---
name: chipflow-evidence
description: Advance and audit this repository's Croc/IHP, Pin3D and OBI memory-extension work using immutable EDA evidence, stage-specific acceptance and bounded experiments.
---

# Chipflow evidence

Read `CURRENT_STATUS.md` first. For a specific run, inspect its current artifacts and source hashes; historical milestone PASS entries describe the acceptance logic at that time. The Windows AI_chip NUMA checkout is a separate project. Run this repository in WSL ext4 with its pinned submodules and tools.

## Choose the relevant track

- Croc/IHP: use `docs/03_signoff_policy_zh.md`, `scripts/collect_croc_evidence.py` and `scripts/parse_croc_signoff.py`. WNS/TNS must be finite and nonnegative; setup, hold, max slew, capacitance and fanout counts must all be observed integer zero. Missing data is unknown, not zero. PDN connectivity is not IR/EM evidence. Aggregate timing is not extracted-parasitic/MMMC qualification.
- Pin3D: inspect the latest HBT capacity and route-only summaries. Preserve `research_only`, actual TECH_LEF dimensions, units and legal pitch. Capacity PASS is not legal HBT placement or route PASS. The historical 530 geometric HBT pairs and remaining 112 markers have different evidence scopes.
- New memory/OBI work: start with `docs/05_memory_spec_zh.md` and its requirement IDs. C1 module work can proceed independently of baseline physical closure. Define observable behavior and an independent scoreboard before optimizing RTL; do not invent real SRAM/DRAM or 3D process collateral.
- External AI tools: consult `docs/04_ai_chip_skills_zh.md` and its pinned research index. Treat third-party skills as source material until deliberately adapted. Preserve this project's tool versions, stage gates and user scope; do not inherit automatic delegation, global memory or installation behavior.

## Evidence and next actions

Keep raw run reports and manifests unchanged. Reassess them under a new run ID with source hashes. `scripts/audit_croc_acceptance.py --source-run runs/<run-id>` reads archived Croc reports without EDA; add `--require-pass` when a shell gate needs a nonzero result for electrical failure. Creating a summary is not passing the design.

For current blocked physical work, follow the explicit next gate in `CURRENT_STATUS.md`: supported IHP leaf/parent evidence before full-chip attempt 3; legal-lattice/window evidence before Pin3D route. Do not rerun full flows to compensate for missing diagnosis. Preserve strict ports, density, antenna, off-grid and pin-access rules. Use bounded experiments with one identified hypothesis, fixed input hashes, independent run IDs and an explicit acceptance criterion.

For code changes run `PYTHONDONTWRITEBYTECODE=1 make test validate-contracts`; use `make report` when report behavior changes. Check patch applicability against the pinned source and inspect all newly staged files before committing. Heavy EDA validation is a separate result: fast Python tests never prove chip closure.

Report architecture, RTL/function, synthesis, physical implementation, and verification separately. Retain DRC counting basis (raw versus merged), source run IDs, tool versions and remaining unknowns. Use current user authorization for routine reversible work; ask only for genuinely missing product/process decisions or actions outside the authorized scope.
