#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reassess immutable Croc reports without starting any EDA process."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from collect_croc_evidence import final_timing, timing_checks

ROOT = Path(__file__).resolve().parents[1]


def audit(source_run: Path) -> dict:
    report = source_run / 'artifacts/pnr/upstream/croc/openroad/reports/05_croc.final.rpt'
    original = source_run / 'stage_evidence/croc-pnr.json'
    if not report.is_file() or not original.is_file():
        raise ValueError('Both archived final report and historical stage evidence are required')
    timing = final_timing(report)
    checks = timing_checks(timing)
    historical = json.loads(original.read_text())
    return {
        'schema_version': '1.0.0',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_run_id': source_run.name,
        'status': 'electrical_acceptance_passed' if all(checks.values()) else 'electrical_acceptance_failed',
        'eda_rerun_performed': False,
        'historical_stage_status': historical['status'],
        'observed_timing': timing,
        'checks': checks,
        'gates': {
            'electrical_acceptance_passed': all(checks.values()),
            'postroute_extracted_sta_proven': False,
            'complete_corner_mode_coverage_proven': False,
            'public_rule_signoff': False,
        },
        'source': {
            'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (report, original)},
        },
        'limitations': [
            'Reassessment preserves historical stage records; no physical repair or EDA rerun is implied.',
            'Library loading and aggregate WNS/TNS do not prove full corner/mode coverage.',
            'The audited baseline uses estimated parasitics; final extracted-SPEF timing was not established.',
            'PDN connectivity does not establish IR-drop/EM or complete IO supply integrity.',
            'A-track DRC and LVS remain failed; this audit never promotes the design to signoff.',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-pass', action='store_true')
    args = parser.parse_args()
    result = audit(args.source_run.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # New audit identities are required; never replace a historical result.
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
    print(json.dumps({'status': result['status'], 'checks': result['checks']}, sort_keys=True))
    return int(args.require_pass and not result['gates']['electrical_acceptance_passed'])


if __name__ == '__main__':
    raise SystemExit(main())
