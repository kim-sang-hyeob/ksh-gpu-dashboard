#!/usr/bin/env python3
"""Send lightweight GPU, disk, and experiment-index heartbeats."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


_vessl_cache: dict = {"valid_until": 0.0, "value": {}}


def run_csv(arguments: list[str]) -> list[list[str]]:
    result = subprocess.run(arguments, check=True, text=True, capture_output=True, timeout=15)
    return [row for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True) if row]


def number(value: str, kind=float):
    value = value.strip()
    if not value or value.lower() in {"n/a", "[not supported]"}:
        return None
    try:
        return kind(float(value))
    except ValueError:
        return None


def gpu_processes() -> dict[str, list[dict]]:
    try:
        rows = run_csv([
            "nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ])
    except (OSError, subprocess.SubprocessError):
        return {}
    result: dict[str, list[dict]] = {}
    for row in rows:
        if len(row) < 4:
            continue
        result.setdefault(row[0].strip(), []).append({
            "pid": number(row[1], int),
            "name": Path(row[2].strip()).name,
            "memory_mib": number(row[3], int),
        })
    return result


def collect_gpus() -> list[dict]:
    processes = gpu_processes()
    rows = run_csv([
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,uuid",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    for row in rows:
        if len(row) < 8:
            continue
        uuid = row[7].strip()
        gpus.append({
            "index": number(row[0], int),
            "name": row[1].strip(),
            "utilization": number(row[2]) or 0,
            "memory_used_mib": number(row[3]) or 0,
            "memory_total_mib": number(row[4]) or 0,
            "temperature_c": number(row[5]),
            "power_w": number(row[6]),
            "processes": processes.get(uuid, []),
        })
    return gpus


def disk(path: str) -> dict | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"used": usage.used, "total": usage.total}


def timestamp_from_run_id(run_id: str) -> str | None:
    match = re.match(r"^(\d{8}T\d{6}Z)", run_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def plain_cell(value: str) -> str:
    match = re.fullmatch(r"\[([^]]+)]\(([^)]+)\)", value.strip())
    return match.group(1) if match else value.strip()


def link_target(value: str) -> str | None:
    match = re.fullmatch(r"\[[^]]+]\(([^)]+)\)", value.strip())
    return match.group(1) if match else None


def markdown_cells(line: str) -> list[str]:
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def run_metadata(index_path: Path, target: str | None) -> dict:
    """Load a small meta.json only when the index link stays inside /root/runs."""
    if not target:
        return {}
    try:
        result_path = (index_path.parent / target).resolve()
        result_path.relative_to(index_path.parent.resolve())
        meta_path = result_path.parent / "meta.json"
        if not meta_path.is_file() or meta_path.stat().st_size > 4096:
            return {}
        value = json.loads(meta_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def collect_runs(index_path: str = "/root/runs/INDEX.md") -> list[dict]:
    path = Path(index_path)
    if not path.is_file():
        return []
    runs = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|"):
            continue
        cells = markdown_cells(line)
        if len(cells) < 7 or cells[0] in {"실험 ID", "Run ID"} or set(cells[0]) <= {"-", ":"}:
            continue
        run_id, purpose, _baseline, status, gpu_ids, updated_at, result = cells[:7]
        target = link_target(result)
        meta = run_metadata(path, target)
        parsed_run_id = plain_cell(run_id)
        parsed_gpu_ids = [] if plain_cell(gpu_ids).upper() == "CPU" else re.findall(r"\d+", plain_cell(gpu_ids))
        project = meta.get("project") or ((target.split("/", 1)[0] if target else "unknown") or "unknown")
        runs.append({
            "run_id": meta.get("run_id") or parsed_run_id,
            "project": project,
            "purpose": meta.get("goal") or plain_cell(purpose),
            "status": str(meta.get("status") or plain_cell(status)).lower(),
            "gpu_ids": [str(item) for item in meta.get("gpu_ids", parsed_gpu_ids)],
            "started_at": meta.get("started_at") or timestamp_from_run_id(parsed_run_id),
            "result_path": str((path.parent / target).resolve()) if target else None,
            "summary": {
                "architecture": meta.get("architecture"),
                "dataset": meta.get("dataset"),
                "ended_at": meta.get("ended_at"),
                "exit_code": meta.get("exit_code"),
                "code_commit": meta.get("code_commit"),
                "resume_count": meta.get("resume_count"),
                "last_checked": meta.get("updated_at") or plain_cell(updated_at),
            },
        })
    return runs[-40:]


def collect_vessl_workspace() -> dict:
    """Read this workspace's current session deadline, cached for five minutes."""
    if time.monotonic() < _vessl_cache["valid_until"]:
        return _vessl_cache["value"]
    value: dict = {}
    workspace_id = os.environ.get("VESSL_WORKSPACE_ID")
    if workspace_id:
        try:
            from vessl.workspace import read_workspace

            workspace = read_workspace(workspace_id=int(workspace_id))
            started_at = getattr(workspace, "status_last_updated", None)
            max_hours = getattr(workspace, "max_running_hours", None)
            expires_at = started_at + timedelta(hours=max_hours) if started_at and max_hours else None
            value = {
                "id": str(workspace.id),
                "status": workspace.status,
                "started_at": started_at.isoformat() if started_at else None,
                "max_running_hours": max_hours,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "url": f"https://app.vessl.ai/{workspace.organization.name}/workspaces/{workspace.id}",
            }
        except Exception:
            value = {}
    _vessl_cache.update(valid_until=time.monotonic() + 300, value=value)
    return value


def payload() -> dict:
    vessl = collect_vessl_workspace()
    return {
        "workspace_id": os.environ["WORKSPACE_ID"],
        "name": os.environ.get("WORKSPACE_NAME", os.environ["WORKSPACE_ID"]),
        "node": os.environ.get("NODE_NAME") or socket.gethostname(),
        "cluster": os.environ.get("CLUSTER_NAME", "cluster-3090"),
        "state": vessl.get("status", "running"),
        "expires_at": vessl.get("expires_at") or os.environ.get("EXPIRES_AT") or None,
        "root": disk("/root"),
        "scratch": disk("/scratch/ksh"),
        "gpus": collect_gpus(),
        "runs": collect_runs(),
        "vessl": vessl,
    }


def send(data: dict) -> str:
    headers = {
        "Authorization": f"Bearer {os.environ['INGEST_KEY']}",
        "Content-Type": "application/json",
        "User-Agent": "ksh-gpu-agent/1.0",
    }
    if os.environ.get("CF_ACCESS_CLIENT_ID"):
        headers["CF-Access-Client-Id"] = os.environ["CF_ACCESS_CLIENT_ID"]
        headers["CF-Access-Client-Secret"] = os.environ["CF_ACCESS_CLIENT_SECRET"]
    request = urllib.request.Request(
        os.environ["DASHBOARD_URL"].rstrip("/") + "/api/heartbeat",
        data=json.dumps(data, separators=(",", ":")).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="collect/send once")
    parser.add_argument("--stdout", action="store_true", help="print payload without sending")
    args = parser.parse_args()
    interval = max(15, int(os.environ.get("INTERVAL_SECONDS", "30")))
    while True:
        try:
            data = payload()
            if args.stdout:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(datetime.now(timezone.utc).isoformat(), send(data), flush=True)
        except (KeyError, OSError, subprocess.SubprocessError, urllib.error.URLError, ValueError) as exc:
            print(datetime.now(timezone.utc).isoformat(), type(exc).__name__, str(exc), flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
