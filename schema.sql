CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  node TEXT,
  cluster_name TEXT,
  state TEXT NOT NULL DEFAULT 'unknown',
  gpu_count INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,
  root_used_bytes INTEGER,
  root_total_bytes INTEGER,
  scratch_used_bytes INTEGER,
  scratch_total_bytes INTEGER,
  last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS gpus (
  workspace_id TEXT NOT NULL,
  gpu_index INTEGER NOT NULL,
  name TEXT NOT NULL,
  utilization REAL NOT NULL DEFAULT 0,
  memory_used_mib REAL NOT NULL DEFAULT 0,
  memory_total_mib REAL NOT NULL DEFAULT 0,
  temperature_c REAL,
  power_w REAL,
  processes_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (workspace_id, gpu_index),
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project TEXT NOT NULL,
  purpose TEXT,
  status TEXT NOT NULL DEFAULT 'unknown',
  gpu_ids TEXT,
  started_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  result_path TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workspaces_last_seen ON workspaces(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_runs_updated_at ON runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
