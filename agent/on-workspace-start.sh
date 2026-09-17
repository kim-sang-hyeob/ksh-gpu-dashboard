#!/usr/bin/env bash

set -u

log_dir=/root/runs/_system/workspace-init
mkdir -p "$log_dir"
exec >>"$log_dir/init.log" 2>&1

printf '%s workspace init start\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p /scratch/ksh/data /scratch/ksh/models /scratch/ksh/generated /scratch/ksh/cache /scratch/ksh/tmp/smoke

agent=/root/work/ksh-gpu-agent/ksh-gpu-agent
if [ -x "$agent" ]; then
  "$agent" start
else
  printf '%s dashboard agent is not installed\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

printf '%s workspace init done\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
