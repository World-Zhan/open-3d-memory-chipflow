#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.digest):
        raise SystemExit(f"invalid image digest: {args.digest}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image_id):
        raise SystemExit(f"invalid local image id: {args.image_id}")
    path = ROOT / "versions.lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["container"]["reference"] != args.reference:
        raise SystemExit("container reference does not match versions.lock.json")
    data["container"]["digest"] = args.digest
    data["container"]["digest_recorded_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    data["container"]["selected_pull_source"] = args.source_reference
    data["container"]["local_image_id"] = args.image_id
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print(f"[LOCK] {args.reference} digest={args.digest} image_id={args.image_id} source={args.source_reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
