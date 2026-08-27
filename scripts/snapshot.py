#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Copy declared artifacts into a run directory and write a SHA-256 inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_source(raw: str) -> tuple[Path, Path]:
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"artifact path must be repository-relative: {raw}")
    src = (ROOT / rel).resolve()
    try:
        src.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"artifact escapes repository: {raw}") from exc
    return rel, src


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    run_dir_raw = os.environ.get("FLOW_RUN_DIR")
    if not run_dir_raw:
        raise SystemExit("FLOW_RUN_DIR is not set; use scripts/run_stage.py")
    run_dir = Path(run_dir_raw).resolve()
    dest_root = run_dir / "artifacts" / args.label
    if dest_root.exists():
        raise SystemExit(f"archive label already exists: {dest_root}")
    dest_root.mkdir(parents=True)

    missing: list[str] = []
    for raw in args.path:
        rel, src = safe_source(raw)
        if not src.exists():
            missing.append(raw)
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, symlinks=True)
        elif src.is_file():
            shutil.copy2(src, dest, follow_symlinks=False)

    if missing and not args.allow_missing:
        raise SystemExit("missing declared artifacts: " + ", ".join(missing))

    inventory = []
    for path in sorted(dest_root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            inventory.append(
                {
                    "path": str(path.relative_to(run_dir)),
                    "bytes": path.stat().st_size,
                    "sha256": digest(path),
                }
            )
    payload = {"label": args.label, "missing": missing, "files": inventory}
    (dest_root / "inventory.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[ARCHIVE] {len(inventory)} files -> {dest_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
