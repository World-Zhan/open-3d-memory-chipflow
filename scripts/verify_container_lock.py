#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-ref", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))
    reference = lock["container"]["reference"]
    expected = lock["container"].get("digest")
    expected_image_id = lock["container"].get("local_image_id")
    if not expected:
        raise SystemExit("container digest is not locked; run 'make docker-pull'")
    proc = subprocess.run(
        ["docker", "image", "inspect", reference, "--format", "{{json .RepoDigests}}"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"container image is missing: {reference}")
    digests = json.loads(proc.stdout)
    actual_values = [item.split("@", 1)[1] for item in digests if "@" in item]
    if expected not in actual_values:
        raise SystemExit(f"container digest mismatch: expected {expected}, actual {actual_values}")
    id_proc = subprocess.run(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    actual_image_id = id_proc.stdout.strip()
    if not expected_image_id or actual_image_id != expected_image_id:
        raise SystemExit(
            f"container image-id mismatch: expected {expected_image_id}, actual {actual_image_id}"
        )
    if args.print_ref:
        print(actual_image_id)
    else:
        print(
            f"[PASS] container lock {reference} digest={expected} image_id={actual_image_id}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
