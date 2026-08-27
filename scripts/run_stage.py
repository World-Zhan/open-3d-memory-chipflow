#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run one named stage with immutable, retry-aware logs and evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import uuid

try:
    import fcntl
except ModuleNotFoundError:  # Allows platform-neutral contract tests on Windows.
    fcntl = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def git_output(*args: str, cwd: Path = ROOT) -> str | None:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=False
    )
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def new_run_id(stage: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{stamp}-{stage}-{suffix}"


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_manifest(path: Path, run_id: str) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "versions.lock.json").read_text(encoding="utf-8"))
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "created_at": utc_now(),
        "repository": {
            "root": str(ROOT),
            "commit": git_output("rev-parse", "HEAD"),
            "dirty": bool(git_output("status", "--porcelain")),
        },
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "locked_versions": lock,
        "stages": [],
    }


def next_attempt(stages: list[dict], stage: str) -> int:
    same_stage = [item for item in stages if item["name"] == stage]
    if not same_stage:
        return 1
    latest = same_stage[-1]
    if latest["status"] != "failed":
        raise ValueError(
            f"stage {stage!r} already has latest status {latest['status']!r}; "
            "only a failed stage may be retried"
        )
    attempts = [item.get("attempt", index) for index, item in enumerate(same_stage, start=1)]
    return max(attempts) + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--stage", required=True)
    parser.add_argument(
        "--requires",
        action="append",
        default=[],
        help="stage name that must already be passed in the same run (repeatable)",
    )
    parser.add_argument(
        "--classification",
        required=True,
        choices=["public_rule_candidate", "research_only"],
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def main() -> int:
    if fcntl is None:
        raise SystemExit("run_stage.py requires a POSIX environment with fcntl (use WSL)")
    args = parse_args()
    run_id = args.run_id or os.environ.get("RUN_ID") or new_run_id(args.stage)
    if not RUN_ID_RE.fullmatch(run_id):
        raise SystemExit("RUN_ID must match [A-Za-z0-9][A-Za-z0-9._-]{0,79}")

    run_dir = ROOT / "runs" / run_id
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / ".manifest.lock"
    manifest_path = run_dir / "manifest.json"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        manifest = load_manifest(manifest_path, run_id)
        try:
            attempt = next_attempt(manifest["stages"], args.stage)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
        stage_instance = args.stage if attempt == 1 else f"{args.stage}.attempt-{attempt}"
        stage_status = {item["name"]: item["status"] for item in manifest["stages"]}
        unmet = [name for name in args.requires if stage_status.get(name) != "passed"]
        if unmet:
            details = ", ".join(
                f"{name}={stage_status.get(name, 'not_run')}" for name in unmet
            )
            print(
                f"[ERROR] stage {args.stage!r} requires passed stages in the same "
                f"run {run_id!r}: {details}",
                file=sys.stderr,
            )
            return 2
        stage_record = {
            "name": args.stage,
            "attempt": attempt,
            "instance": stage_instance,
            "classification": args.classification,
            "requires": args.requires,
            "status": "running",
            "started_at": utc_now(),
            "finished_at": None,
            "command": args.command,
            "command_display": shlex.join(args.command),
            "log": f"logs/{stage_instance}.log",
            "exit_code": None,
            "evidence": None,
        }
        manifest["stages"].append(stage_record)
        atomic_json(manifest_path, manifest)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    env = os.environ.copy()
    env.update(
        {
            "FLOW_RUN_ID": run_id,
            "FLOW_RUN_DIR": str(run_dir),
            "FLOW_STAGE": args.stage,
            "FLOW_STAGE_INSTANCE": stage_instance,
            "FLOW_ATTEMPT": str(attempt),
            "FLOW_ATTEMPT_SUFFIX": "" if attempt == 1 else f".attempt-{attempt}",
            "PYTHONUNBUFFERED": "1",
        }
    )
    log_path = logs_dir / f"{stage_instance}.log"
    print(f"[RUN] id={run_id} stage={args.stage} attempt={attempt}")
    print(f"[RUN] log={log_path}")

    with log_path.open("x", encoding="utf-8", errors="replace") as log:
        log.write(f"started_at={stage_record['started_at']}\n")
        log.write(f"command={stage_record['command_display']}\n")
        log.flush()
        proc = subprocess.Popen(
            args.command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
        exit_code = proc.wait()

    evidence_path = run_dir / "stage_evidence" / f"{stage_instance}.json"
    evidence = None
    if evidence_path.is_file():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            evidence = {"parse_error": str(exc), "path": str(evidence_path.relative_to(run_dir))}

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in reversed(manifest["stages"]):
            if item["name"] == args.stage and item.get("attempt", 1) == attempt:
                item["status"] = "passed" if exit_code == 0 else "failed"
                item["finished_at"] = utc_now()
                item["exit_code"] = exit_code
                item["evidence"] = evidence
                break
        atomic_json(manifest_path, manifest)

    print(f"[RUN] completed id={run_id} stage={args.stage} attempt={attempt} exit_code={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
