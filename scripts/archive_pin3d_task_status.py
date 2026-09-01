#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Archive one terminal TaiWei status so a new monitored task can start."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATUSES = {"ok", "failed"}
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def archive_terminal_status(
    status_file: Path,
    run_dir: Path,
    label: str,
    *,
    status_root: Path | None = None,
    runs_root: Path | None = None,
) -> Path | None:
    if not LABEL_RE.fullmatch(label):
        raise ValueError(f"unsafe status archive label: {label!r}")
    allowed_status_root = (status_root or ROOT / "upstream/taiwei-pin-3d/run_logs/status").resolve()
    allowed_runs_root = (runs_root or ROOT / "runs").resolve()
    resolved_status = status_file.resolve()
    resolved_run = run_dir.resolve()
    if resolved_status.parent != allowed_status_root:
        raise ValueError(f"status file is outside the expected directory: {resolved_status}")
    if allowed_runs_root not in resolved_run.parents:
        raise ValueError(f"run directory is outside {allowed_runs_root}: {resolved_run}")
    if not resolved_status.is_file():
        print(f"[PIN3D][TASK] no prior status to archive: {resolved_status}")
        return None

    payload = json.loads(resolved_status.read_text(encoding="utf-8"))
    status = str(payload.get("status", "unknown"))
    if status not in TERMINAL_STATUSES:
        raise RuntimeError(f"refusing to archive nonterminal task status={status}")

    archive_dir = resolved_run / "scheduler_state"
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / f"{resolved_status.stem}.{label}.pre.json"
    if destination.exists():
        raise FileExistsError(f"status archive already exists: {destination}")
    resolved_status.replace(destination)
    print(f"[PIN3D][TASK] archived prior terminal status={status}: {destination}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    try:
        archive_terminal_status(args.status_file, args.run_dir, args.label)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[PIN3D][TASK][ERROR] cannot prepare scheduler state: {exc}")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
