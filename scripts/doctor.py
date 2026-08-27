#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only audit of WSL resources, tools, locks, submodules and container state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def command(args: list[str], cwd: Path = ROOT, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args, cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    return values


def add(checks: list[dict], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def git_head(path: Path) -> str | None:
    code, output = command(["git", "rev-parse", "HEAD"], cwd=path)
    return output if code == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--human", action="store_true")
    output.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checks: list[dict] = []
    lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))

    release = platform.release().lower()
    add(checks, "wsl2", "pass" if "microsoft" in release else "fail", platform.release())
    root_text = str(ROOT)
    add(checks, "ext4-path", "fail" if root_text.startswith("/mnt/") else "pass", root_text)

    cpus = os.cpu_count() or 0
    add(checks, "cpu", "pass" if cpus >= 6 else "fail", f"{cpus} logical processors; flow cap=6")
    memory = meminfo()
    gib = 1024 ** 3
    mem_gib = memory.get("MemTotal", 0) / gib
    swap_gib = memory.get("SwapTotal", 0) / gib
    add(checks, "memory", "pass" if mem_gib >= 9 else "fail", f"{mem_gib:.1f} GiB visible")
    add(checks, "swap", "pass" if swap_gib >= 10 else "fail", f"{swap_gib:.1f} GiB visible")
    disk = shutil.disk_usage(ROOT)
    free_gib = disk.free / gib
    add(checks, "disk", "pass" if free_gib >= 100 else "fail", f"{free_gib:.1f} GiB free")

    for tool in ("git", "make", "python3"):
        location = shutil.which(tool)
        add(checks, f"tool:{tool}", "pass" if location else "fail", location or "not found")

    for name, entry in lock["upstreams"].items():
        path_value = entry.get("path")
        expected = entry.get("commit")
        if not path_value:
            continue
        actual = git_head(ROOT / path_value)
        status = "pass" if actual == expected else "fail"
        add(checks, f"lock:{name}", status, f"expected={expected} actual={actual}")

    code, submodules = command(["git", "submodule", "status", "--recursive"], timeout=60)
    bad = [line for line in submodules.splitlines() if line[:1] in {"-", "+", "U"}]
    add(
        checks,
        "submodules",
        "pass" if code == 0 and not bad else "fail",
        "all initialized at gitlinks" if code == 0 and not bad else "; ".join(bad[:8]) or submodules,
    )

    docker = shutil.which("docker")
    add(checks, "tool:docker", "pass" if docker else "fail", docker or "not installed")
    compose_ok = False
    docker_info_ok = False
    if docker:
        code, text = command(["docker", "compose", "version"])
        compose_ok = code == 0
        add(checks, "docker-compose", "pass" if compose_ok else "fail", text)
        code, text = command(["docker", "info", "--format", "{{.ServerVersion}}"])
        docker_info_ok = code == 0
        add(checks, "docker-engine", "pass" if docker_info_ok else "fail", text)
    else:
        add(checks, "docker-compose", "fail", "docker CLI unavailable")
        add(checks, "docker-engine", "fail", "docker CLI unavailable")

    image = lock["container"]["reference"]
    expected_digest = lock["container"].get("digest")
    actual_digest = None
    if docker_info_ok:
        code, text = command(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"])
        if code == 0:
            try:
                values = json.loads(text)
                if values:
                    actual_digest = values[0].split("@", 1)[1]
            except (json.JSONDecodeError, IndexError):
                pass
    image_status = "pass" if actual_digest else "fail"
    add(checks, "croc-image", image_status, actual_digest or f"missing: {image}")
    if actual_digest:
        if expected_digest is None:
            add(checks, "image-digest-lock", "warn", "image exists but digest has not been recorded")
        else:
            add(checks, "image-digest-lock", "pass" if actual_digest == expected_digest else "fail", f"expected={expected_digest} actual={actual_digest}")
    else:
        add(checks, "image-digest-lock", "fail", "cannot compare without a local image")

    orfs_bins = {
        "openroad": ROOT / "upstream/orfs-research/tools/install/OpenROAD/bin/openroad",
        "sta": ROOT / "upstream/orfs-research/tools/install/OpenROAD/bin/sta",
        "yosys": ROOT / "upstream/orfs-research/tools/install/yosys/bin/yosys",
    }
    for name, path in orfs_bins.items():
        add(checks, f"orfs:{name}", "pass" if os.access(path, os.X_OK) else "fail", str(path))

    try:
        socket.getaddrinfo("github.com", 443)
        add(checks, "dns:github.com", "pass", "resolved")
    except OSError as exc:
        add(checks, "dns:github.com", "warn", str(exc))

    payload = {
        "schema_version": "1.0.0",
        "root": str(ROOT),
        "overall": "fail" if any(c["status"] == "fail" for c in checks) else "pass",
        "checks": checks,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        width = max(len(item["name"]) for item in checks)
        for item in checks:
            print(f"[{item['status'].upper():4}] {item['name']:<{width}}  {item['detail']}")
        print(f"\nDoctor overall: {payload['overall'].upper()}")
    return 1 if payload["overall"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
