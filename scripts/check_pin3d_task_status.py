#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Convert TaiWei's monitored task status JSON into a reliable exit code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STATUS_ERROR = 4


def task_exit_code(payload: dict) -> int:
    status = str(payload.get("status", "unknown"))
    dispatch_rc = payload.get("dispatch_rc")
    if status == "ok" and dispatch_rc in (None, 0):
        return 0
    if isinstance(dispatch_rc, int) and not isinstance(dispatch_rc, bool) and dispatch_rc != 0:
        return dispatch_rc
    return STATUS_ERROR


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    if not args.status_file.is_file():
        print(f"[PIN3D][TASK][ERROR] missing status file: {args.status_file}")
        return STATUS_ERROR
    try:
        payload = json.loads(args.status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[PIN3D][TASK][ERROR] cannot parse {args.status_file}: {exc}")
        return STATUS_ERROR

    exit_code = task_exit_code(payload)
    print(
        "[PIN3D][TASK] "
        f"status={payload.get('status', 'unknown')} "
        f"phase={payload.get('phase', 'unknown')} "
        f"dispatch_rc={payload.get('dispatch_rc')} "
        f"exit_code={exit_code}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
