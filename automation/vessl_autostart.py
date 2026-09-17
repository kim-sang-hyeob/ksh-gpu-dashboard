"""Start selected VESSL workspaces when their current status is stopped."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable

INIT_SCRIPT = "bash /root/work/server-setup/on-workspace-start.sh"


def parse_workspace_ids(value: str) -> list[str]:
    workspace_ids: list[str] = []
    for raw in value.split(","):
        workspace_id = raw.strip()
        if not workspace_id:
            continue
        if not re.fullmatch(r"[1-9][0-9]*", workspace_id):
            raise ValueError("Workspace selectors must be positive numeric IDs")
        if workspace_id not in workspace_ids:
            workspace_ids.append(workspace_id)
    if not workspace_ids:
        raise ValueError("At least one workspace ID is required")
    return workspace_ids


def read_statuses(workspace_ids: Iterable[str], organization: str) -> dict[str, str]:
    # VESSL may print request details. Keep public Actions logs limited to counts.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import vessl
        from vessl.workspace import read_workspace

        vessl.vessl_api.api_client.configuration.verify_ssl = True
        return {
            workspace_id: str(
                read_workspace(
                    int(workspace_id),
                    organization_name=organization,
                ).status
            ).lower()
            for workspace_id in workspace_ids
        }


def request_start(workspace_id: str) -> None:
    try:
        result = subprocess.run(
            ["vessl", "workspace", "start", workspace_id],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "VESSL_SAVE_CONFIG": "false"},
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("VESSL start request failed or timed out") from error
    if result.returncode:
        raise RuntimeError("VESSL start request failed")


def configure_init_script(workspace_id: str) -> None:
    organization = os.environ["VESSL_DEFAULT_ORGANIZATION"].strip()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import vessl

        vessl.vessl_api.workspace_update_api(
            organization,
            int(workspace_id),
            workspace_update_api_input={"init_script": INIT_SCRIPT},
            _request_timeout=30,
        )


def process(
    statuses: dict[str, str],
    starter: Callable[[str], None] = request_start,
    configurator: Callable[[str], None] = configure_init_script,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    stopped = [workspace_id for workspace_id, status in statuses.items() if status == "stopped"]
    if dry_run:
        return len(stopped), 0

    failures = 0
    for workspace_id in stopped:
        try:
            configurator(workspace_id)
            starter(workspace_id)
        except Exception:
            failures += 1
    return len(stopped), failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        workspace_ids = parse_workspace_ids(os.environ["VESSL_WORKSPACE_IDS"])
        organization = os.environ["VESSL_DEFAULT_ORGANIZATION"].strip()
        if not organization:
            raise ValueError("VESSL_DEFAULT_ORGANIZATION is empty")
        statuses = read_statuses(workspace_ids, organization)
        stopped, failures = process(statuses, dry_run=args.dry_run)
    except Exception:
        print("VESSL workspace check failed; verify credentials and configured IDs.", file=sys.stderr)
        return 1

    running = sum(status == "running" for status in statuses.values())
    other = len(statuses) - running - stopped
    action = "would request" if args.dry_run else "requested"
    print(
        f"Checked {len(statuses)} workspace(s): running={running}, stopped={stopped}, "
        f"other={other}; starts {action}={stopped - failures}, failures={failures}."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
