import html from "./dashboard.html";

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

const response = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: JSON_HEADERS });

async function status(env) {
  const [workspaceResult, gpuResult, runResult] = await env.DB.batch([
    env.DB.prepare("SELECT * FROM workspaces ORDER BY last_seen DESC"),
    env.DB.prepare("SELECT * FROM gpus ORDER BY workspace_id, gpu_index"),
    env.DB.prepare("SELECT * FROM runs ORDER BY updated_at DESC LIMIT 40")
  ]);
  const workspaces = workspaceResult.results.map(w => {
    let payload = {};
    try { payload = JSON.parse(w.payload_json || "{}"); } catch {}
    return {
      ...w,
      expires_at: w.expires_at || payload.expires_at || payload.vessl?.expires_at || null,
      gpus: []
    };
  });
  const map = new Map(workspaces.map(w => [w.id, w]));
  for (const gpu of gpuResult.results) map.get(gpu.workspace_id)?.gpus.push(gpu);
  return { workspaces, runs: runResult.results, server_time: new Date().toISOString() };
}

function validHeartbeat(body) {
  return body && typeof body.workspace_id === "string" && body.workspace_id.length <= 80 &&
    typeof body.name === "string" && Array.isArray(body.gpus) && body.gpus.length <= 32;
}

async function heartbeat(request, env) {
  const expected = env.INGEST_KEY;
  if (!expected || request.headers.get("authorization") !== `Bearer ${expected}`) return response({ error: "unauthorized" }, 401);
  const body = await request.json().catch(() => null);
  if (!validHeartbeat(body)) return response({ error: "invalid heartbeat" }, 400);
  const statements = [env.DB.prepare(`INSERT INTO workspaces
    (id,name,node,cluster_name,state,gpu_count,expires_at,root_used_bytes,root_total_bytes,scratch_used_bytes,scratch_total_bytes,last_seen,payload_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?)
    ON CONFLICT(id) DO UPDATE SET name=excluded.name,node=excluded.node,cluster_name=excluded.cluster_name,state=excluded.state,
    gpu_count=excluded.gpu_count,expires_at=excluded.expires_at,root_used_bytes=excluded.root_used_bytes,root_total_bytes=excluded.root_total_bytes,
    scratch_used_bytes=excluded.scratch_used_bytes,scratch_total_bytes=excluded.scratch_total_bytes,last_seen=CURRENT_TIMESTAMP,payload_json=excluded.payload_json`)
    .bind(body.workspace_id, body.name, body.node ?? null, body.cluster ?? null, body.state ?? "running", body.gpus.length,
      body.expires_at ?? null, body.root?.used ?? null, body.root?.total ?? null, body.scratch?.used ?? null, body.scratch?.total ?? null, JSON.stringify(body)),
    env.DB.prepare("DELETE FROM gpus WHERE workspace_id=?").bind(body.workspace_id)];
  for (const g of body.gpus) statements.push(env.DB.prepare(`INSERT INTO gpus
    (workspace_id,gpu_index,name,utilization,memory_used_mib,memory_total_mib,temperature_c,power_w,processes_json,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)`).bind(body.workspace_id, Number(g.index), String(g.name ?? "GPU"), Number(g.utilization ?? 0),
      Number(g.memory_used_mib ?? 0), Number(g.memory_total_mib ?? 0), g.temperature_c ?? null, g.power_w ?? null, JSON.stringify(g.processes ?? [])));
  for (const r of body.runs ?? []) statements.push(env.DB.prepare(`INSERT INTO runs
    (run_id,workspace_id,project,purpose,status,gpu_ids,started_at,updated_at,result_path,summary_json)
    VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?,?) ON CONFLICT(run_id) DO UPDATE SET workspace_id=excluded.workspace_id,project=excluded.project,
    purpose=excluded.purpose,status=excluded.status,gpu_ids=excluded.gpu_ids,started_at=excluded.started_at,
    updated_at=CURRENT_TIMESTAMP,result_path=excluded.result_path,summary_json=excluded.summary_json`).bind(String(r.run_id), body.workspace_id,
      String(r.project ?? "unknown"), r.purpose ?? null, String(r.status ?? "unknown"), JSON.stringify(r.gpu_ids ?? []), r.started_at ?? null,
      r.result_path ?? null, JSON.stringify(r.summary ?? {})));
  await env.DB.batch(statements);
  return response({ ok: true, received_at: new Date().toISOString() });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
    if (request.method === "GET" && url.pathname === "/api/status") return response(await status(env));
    if (request.method === "POST" && url.pathname === "/api/heartbeat") return heartbeat(request, env);
    if (request.method === "GET" && url.pathname === "/api/health") return response({ ok: true });
    return response({ error: "not found" }, 404);
  }
};
