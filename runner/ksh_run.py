#!/usr/bin/env python3
"""Small, dependency-free experiment launcher for the KSH GPU workspaces."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


MAX_META_BYTES = 4096
INDEX_HEADER = """# 실험 목록

| 실험 ID | 목적 | 기준 실험 | 상태 | GPU | 마지막 확인 시각 | 결과 경로 |
|---|---|---|---|---|---|---|
"""
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_time(value: str | None = None) -> str:
    stamp = value or utc_now()
    return stamp.replace("-", "").replace(":", "").replace("Z", "Z")


def runs_root() -> Path:
    return Path(os.environ.get("KSH_RUNS_ROOT", "/root/runs")).expanduser().resolve()


def smoke_root() -> Path:
    return Path(os.environ.get("KSH_SMOKE_ROOT", "/scratch/ksh/tmp/smoke")).expanduser().resolve()


def validate_name(value: str, label: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        raise ValueError(f"{label} must match {SAFE_NAME.pattern!r}: {value!r}")
    return value


def parse_gpus(value: str) -> list[str]:
    text = value.strip().lower()
    if text in {"", "cpu", "none"}:
        return []
    result: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if not item.isdigit() or not 0 <= int(item) <= 31:
            raise ValueError(f"invalid GPU id: {item!r}")
        normalized = str(int(item))
        if normalized not in result:
            result.append(normalized)
    return result


def markdown_cell(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ").strip() or "—"


def atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_meta(run_dir: Path) -> dict:
    return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))


def write_meta(run_dir: Path, meta: dict) -> None:
    encoded = json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_META_BYTES:
        raise ValueError(f"meta.json exceeds {MAX_META_BYTES} bytes")
    atomic_write(run_dir / "meta.json", encoded)


def git_commit(workdir: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return proc.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def workspace_name() -> str:
    for key in ("KSH_SERVER_NAME", "VESSL_WORKSPACE_NAME", "WORKSPACE_NAME"):
        value = os.environ.get(key, "").strip()
        if value:
            return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:40]
    env_path = Path("/root/.config/ksh-gpu-agent/env")
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, raw = line.partition("=")
            if separator and key.strip() == "WORKSPACE_NAME":
                value = raw.strip().strip("'\"")
                if value:
                    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:40]
    except OSError:
        pass
    return re.sub(r"[^A-Za-z0-9._-]+", "-", socket.gethostname()).strip("-")[:40] or "workspace"


def render_index_row(meta: dict) -> str:
    gpu_text = ",".join(str(item) for item in meta.get("gpu_ids", [])) or "CPU"
    relative = f"{meta['project']}/{meta['run_id']}/README.md"
    checked = meta.get("ended_at") or meta.get("updated_at") or meta.get("started_at") or "—"
    values = [
        meta["run_id"],
        meta.get("goal", "—"),
        meta.get("baseline", "—"),
        meta.get("status", "unknown"),
        gpu_text,
        checked,
        f"[기록]({relative})",
    ]
    return "| " + " | ".join(markdown_cell(value) for value in values) + " |"


def update_index(meta: dict) -> None:
    root = runs_root()
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / "INDEX.md"
    lock_path = root / ".index.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        text = index_path.read_text(encoding="utf-8") if index_path.exists() else INDEX_HEADER
        lines = text.rstrip().splitlines()
        row = render_index_row(meta)
        replaced = False
        for position, line in enumerate(lines):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and cells[0] == meta["run_id"]:
                lines[position] = row
                replaced = True
                break
        if not replaced:
            lines.append(row)
        atomic_write(index_path, "\n".join(lines) + "\n")


def create_readme(meta: dict, command: list[str], workdir: Path) -> str:
    gpu_text = ", ".join(meta["gpu_ids"]) or "CPU"
    return f"""# {meta['run_id']}

- 목표: {meta['goal']}
- 구조: {meta['architecture']}
- 데이터셋: {meta['dataset']}
- GPU: {gpu_text}
- 시작: {meta['started_at']}
- 작업 디렉터리: `{workdir}`

## 실행 명령

```bash
{shlex.join(command)}
```

## 결과 메모

실험이 끝난 뒤 핵심 결과만 여기에 남긴다.
"""


def write_environment(run_dir: Path, workdir: Path, commit: str | None) -> None:
    lines = [
        f"python={sys.version.split()[0]}",
        f"hostname={socket.gethostname()}",
        f"workdir={workdir}",
        f"git_commit={commit or 'unknown'}",
    ]
    atomic_write(run_dir / "environment.txt", "\n".join(lines) + "\n")


def prepare_formal(args: argparse.Namespace, command: list[str]) -> Path:
    project = validate_name(args.project, "project")
    gpus = parse_gpus(args.gpu)
    workdir = Path(args.workdir or os.getcwd()).expanduser().resolve()
    if not workdir.is_dir():
        raise ValueError(f"workdir does not exist: {workdir}")

    started_at = utc_now()
    run_id = args.run_id or f"{compact_time(started_at)}_{workspace_name()}_{project}"
    validate_name(run_id, "run-id")
    run_dir = runs_root() / project / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "logs").mkdir()
    (run_dir / "checkpoints").mkdir()

    commit = git_commit(workdir)
    meta = {
        "architecture": args.architecture,
        "baseline": args.baseline,
        "code_commit": commit,
        "dataset": args.dataset,
        "ended_at": None,
        "goal": args.goal,
        "gpu_ids": gpus,
        "project": project,
        "resume_count": 0,
        "run_id": run_id,
        "started_at": started_at,
        "status": "planned",
        "updated_at": started_at,
        "workspace": workspace_name(),
    }
    write_meta(run_dir, meta)
    atomic_write(run_dir / "README.md", create_readme(meta, command, workdir))
    atomic_write(run_dir / "command.sh", f"#!/usr/bin/env bash\nset -euo pipefail\ncd {shlex.quote(str(workdir))}\nexport CUDA_VISIBLE_DEVICES={shlex.quote(','.join(gpus))}\nexec {shlex.join(command)}\n", 0o755)
    write_environment(run_dir, workdir, commit)
    launch = {"command": command, "gpu_ids": gpus, "workdir": str(workdir)}
    atomic_write(run_dir / "launch.json", json.dumps(launch, ensure_ascii=False, indent=2) + "\n", 0o600)
    update_index(meta)
    return run_dir


def supervise(run_dir: Path) -> int:
    run_dir = run_dir.expanduser().resolve()
    launch = json.loads((run_dir / "launch.json").read_text(encoding="utf-8"))
    meta = read_meta(run_dir)
    env = os.environ.copy()
    if launch["gpu_ids"]:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(launch["gpu_ids"])
    else:
        env.pop("CUDA_VISIBLE_DEVICES", None)
    env["KSH_RUN_ID"] = meta["run_id"]
    env["KSH_RUN_DIR"] = str(run_dir)

    meta["status"] = "running"
    meta["updated_at"] = utc_now()
    meta["supervisor_pid"] = os.getpid()
    write_meta(run_dir, meta)
    update_index(meta)

    exit_code = 1
    try:
        with (run_dir / "logs" / "stdout.log").open("ab", buffering=0) as log:
            process = subprocess.Popen(
                launch["command"],
                cwd=launch["workdir"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            atomic_write(run_dir / "process.pid", f"{process.pid}\n")
            meta["process_pid"] = process.pid
            meta["updated_at"] = utc_now()
            write_meta(run_dir, meta)
            exit_code = process.wait()
    except Exception as exc:  # Preserve failure details in the run record.
        atomic_write(run_dir / "logs" / "launcher-error.log", f"{type(exc).__name__}: {exc}\n")
        exit_code = 125
    finally:
        meta = read_meta(run_dir)
        ended_at = utc_now()
        meta["ended_at"] = ended_at
        meta["exit_code"] = exit_code
        meta["status"] = "completed" if exit_code == 0 else "failed"
        meta["updated_at"] = ended_at
        write_meta(run_dir, meta)
        update_index(meta)
    return exit_code


def run_smoke(args: argparse.Namespace, command: list[str]) -> int:
    project = validate_name(args.project, "project")
    gpus = parse_gpus(args.gpu)
    root = smoke_root()
    root.mkdir(parents=True, exist_ok=True)
    smoke_dir = Path(tempfile.mkdtemp(prefix=f"{project}-", dir=root)).resolve()
    env = os.environ.copy()
    if gpus:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(gpus)
    else:
        env.pop("CUDA_VISIBLE_DEVICES", None)
    env["KSH_SMOKE_DIR"] = str(smoke_dir)
    print(f"smoke_dir={smoke_dir}", flush=True)
    try:
        return subprocess.run(command, cwd=smoke_dir, env=env, check=False).returncode
    finally:
        if smoke_dir != root and root in smoke_dir.parents:
            shutil.rmtree(smoke_dir, ignore_errors=False)
        print(f"smoke_cleaned={smoke_dir}", flush=True)


def normalize_command(command: list[str]) -> list[str]:
    normalized = list(command)
    if normalized and normalized[0] == "--":
        normalized.pop(0)
    if not normalized:
        raise ValueError("a command is required after --")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ksh-run",
        description="Launch a tracked experiment or a disposable smoke test.",
    )
    parser.add_argument("--project", required=True, help="short project name")
    parser.add_argument("--gpu", default="cpu", help="comma-separated local GPU ids, or cpu")
    parser.add_argument("--goal", required=True, help="one-line experiment goal")
    parser.add_argument("--architecture", default="unspecified", help="one-line model architecture")
    parser.add_argument("--dataset", default="unspecified", help="dataset name/version")
    parser.add_argument("--baseline", default="—", help="baseline run id")
    parser.add_argument("--workdir", help="working directory for a formal experiment")
    parser.add_argument("--run-id", help="explicit unique run id")
    parser.add_argument("--wait", action="store_true", help="stay attached and return the experiment exit code")
    parser.add_argument("--smoke", action="store_true", help="run in disposable scratch space without metadata")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_supervise":
        if len(argv) != 2:
            print("usage: ksh-run _supervise RUN_DIR", file=sys.stderr)
            return 2
        return supervise(Path(argv[1]))

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command = normalize_command(args.command)
        if args.smoke:
            return run_smoke(args, command)
        run_dir = prepare_formal(args, command)
        if args.wait:
            return supervise(run_dir)
        supervisor = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_supervise", str(run_dir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        atomic_write(run_dir / "supervisor.pid", f"{supervisor.pid}\n")
        print(f"run_id={run_dir.name}")
        print(f"run_dir={run_dir}")
        print(f"supervisor_pid={supervisor.pid}")
        return 0
    except (ValueError, FileExistsError, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
