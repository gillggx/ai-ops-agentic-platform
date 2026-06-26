"""AIOps Pipeline-Builder — remote MCP server (runs on EC2).

Lets an external Claude (Claude Desktop / cowork) build an analysis pipeline the
way a human does: discover blocks, preview data to learn its shape, assemble the
pipeline JSON, validate, run, and save — all through MCP tools that proxy the
in-cluster builder API (Java :8002 /internal/* + sidecar :8050 /internal/pipeline/*).

The server holds the internal service tokens; the only thing exposed publicly is
this MCP endpoint (gated by a bearer token at nginx). No build on EC2 — pure
Python (mcp + httpx) in a venv.

Run:  uvicorn server:app  (ASGI)   |   python server.py  (standalone)
Env:  SIDECAR_SERVICE_TOKEN, JAVA_INTERNAL_TOKEN, [SIDECAR_URL], [JAVA_URL],
      [PUBLIC_BASE]  (for view/edit URLs in save_pipeline results)
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

SIDECAR = os.environ.get("SIDECAR_URL", "http://localhost:8050").rstrip("/")
JAVA = os.environ.get("JAVA_URL", "http://localhost:8002").rstrip("/")
SVC = os.environ.get("SIDECAR_SERVICE_TOKEN", "")
JIT = os.environ.get("JAVA_INTERNAL_TOKEN", "")
# shared-secret Bearer for user-facing /api/v1/* (SharedSecretAuthFilter -> IT_ADMIN);
# /internal/* uses JIT (X-Internal-Token). These are different tokens.
SHARED = os.environ.get("SHARED_SECRET_TOKEN", "")
PUBLIC = os.environ.get("PUBLIC_BASE", "https://aiops-gill.com").rstrip("/")

_SH = {"X-Service-Token": SVC, "Content-Type": "application/json"}
_JH = {"X-Internal-Token": JIT, "Content-Type": "application/json"}

INSTRUCTIONS = """\
You build semiconductor-ops analysis pipelines on the AIOps platform by composing
typed "blocks" into a DAG, then running it. Work like a careful human, not by
guessing: discover -> preview -> assemble -> validate -> run -> save.

THE PIPELINE JSON you assemble + pass around:
  {"version":"1.0","name":"...","inputs":[],
   "nodes":[{"id":"n1","block_id":"block_process_history","block_version":"1.0.0",
             "params":{...}}],   # node positions are NOT needed; the UI lays out
   "edges":[{"id":"e1","from":{"node":"n1","port":"data"},
             "to":{"node":"n2","port":"data"}}]}

WORKFLOW (always in this order):
 1. list_blocks() to see what exists; explain_block(name) to read a block's real
    params/description/examples. NEVER guess params — they come from explain_block.
 2. Add the SOURCE node first (e.g. block_process_history) and preview(pj, node_id)
    it to LEARN the actual column names + that rows>0 before wiring downstream.
 3. Build the rest using the columns you saw; preview each new node.
 4. validate(pj) — fix any errors it reports, then run.
 5. execute(pj) — confirm status=success and the chart/table came out.
 6. save_pipeline(name, pj) — returns an id + a view URL for the human to review.

GOTCHAS (learned the hard way — follow these):
 - block_process_history defaults time_range="24h"; sim data may be older, so a
   24h window returns 0 rows. If preview shows rows=0, widen time_range (e.g.
   "7d"/"30d") or pick a known-good tool/step via block_list_objects first.
 - For "all machines / 全廠" use block_list_objects(kind='tool') -> block_mcp_foreach
   -> block_unnest, NOT a single process_history (that's one machine only).
 - Multiple ids: do NOT comma-pack tool_id; leave the source field unset and filter
   downstream with block_filter operator='in' value=[...].
 - For a ranked bar ("由多到少/top-N") set block_bar_chart order='desc' — no separate
   sort block needed; block_pareto self-sorts.
 - Chart output is in execute()'s result_summary.charts[].chart_spec.
Be economical: a few inspect/preview calls, then build. Don't loop blindly.

AUTO-CHECK RULES (rule_* tools) — build a "watch X, alarm, auto-diagnose" rule:
A rule = TRIGGER (when) + CONFIRM/CHECKLIST (what to check, each a pipeline ending
in block_step_check) + the platform fires the alarm. Build the WHOLE rule, then let
the user review it once in our GUI — do NOT review per-checkpoint.
 1. rule_describe_options() for the shapes; ask the user WHAT to watch.
 2. rule_create(title, stage, trigger_config) — stage=patrol (watch) or diagnose.
 3. For each checkpoint: BUILD a check pipeline with the pipeline tools (it MUST end
    in block_step_check — outputs a pass:bool; do NOT add block_alert), save_pipeline,
    then rule_bind_checkpoint(slot='confirm' or 'step:NEW', ...). Build them all; don't
    stop to make the user review each one.
 4. rule_validate(slug); fix issues.
 5. rule_request_review(slug) -> returns a launch_url. Give it to the user: our GUI
    try-runs the WHOLE rule and shows every checkpoint's result together, where they
    edit any one or activate it. THIS is the review step.
DRAFT edits (rule_create/update/bind/set_confirm_check_nl/add_step_nl) run directly —
no confirm needed (they only make a reversible draft).
GOING LIVE / DISABLE / DELETE never happen from a tool. Use rule_request_activate /
rule_request_disable / rule_request_delete — each returns a launch_url; give it to the
user, who confirms in our GUI where the action actually runs. For edits, rule_get ->
rule_update(patch the named part) -> rule_request_review again.
"""

# Server binds 127.0.0.1 only and sits behind nginx (TLS + secret path) — that is
# the trust boundary, so disable FastMCP's auto host-check (it would otherwise
# reject nginx's proxied Host header with HTTP 421 "Invalid Host header").
mcp = FastMCP(
    "aiops-pipeline-builder",
    instructions=INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _get(client: httpx.AsyncClient, url: str, headers: dict) -> Any:
    r = await client.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


async def _post(client: httpx.AsyncClient, url: str, headers: dict, body: dict, timeout: float = 180) -> Any:
    r = await client.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _unwrap(d: Any) -> Any:
    return d.get("data") if isinstance(d, dict) and "data" in d else d


def _parse(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


@mcp.tool()
async def list_blocks(category: str | None = None) -> list[dict]:
    """List the available pipeline blocks (id + category + one-line summary).
    Optionally filter by category: source | transform | logic | output | check.
    Use explain_block(name) to get a block's full params before using it."""
    async with httpx.AsyncClient() as c:
        blocks = _unwrap(await _get(c, f"{JAVA}/internal/blocks", _JH))
    out = []
    for b in blocks or []:
        if category and b.get("category") != category:
            continue
        desc = (b.get("description") or "").strip().splitlines()
        summary = next((ln for ln in desc if ln and not ln.startswith("==")), "")
        out.append({"name": b.get("name"), "category": b.get("category"), "summary": summary[:140]})
    return out


@mcp.tool()
async def explain_block(name: str) -> dict:
    """Get one block's full definition: description, param_schema (the params you
    may set + their types/enums), examples, and input/output ports. This is the
    ONLY source of truth for how to configure a block — never guess params."""
    async with httpx.AsyncClient() as c:
        blocks = _unwrap(await _get(c, f"{JAVA}/internal/blocks", _JH))
    b = next((x for x in (blocks or []) if x.get("name") == name), None)
    if not b:
        return {"error": f"block '{name}' not found", "hint": "call list_blocks() for valid names"}
    return {
        "name": b.get("name"),
        "category": b.get("category"),
        "description": b.get("description"),
        "param_schema": _parse(b.get("param_schema")),
        "input_schema": _parse(b.get("input_schema")) or b.get("input_schema"),
        "output_schema": _parse(b.get("output_schema")) or b.get("output_schema"),
        "examples": _parse(b.get("examples")) or b.get("examples"),
    }


@mcp.tool()
async def validate(pipeline_json: dict) -> dict:
    """Structurally validate a pipeline (topo sort, block existence, ports, params)
    without running real I/O. Returns {ok, status, errors:[...]}. Fix errors, then
    preview/execute."""
    async with httpx.AsyncClient() as c:
        r = await _post(c, f"{SIDECAR}/internal/pipeline/validate", _SH, {"pipeline_json": pipeline_json}, 60)
    return {"ok": r.get("ok"), "status": r.get("status"),
            "errors": r.get("errors") or ([{"error": r.get("error")}] if r.get("error") else []),
            "terminal_nodes": r.get("terminal_nodes")}


@mcp.tool()
async def preview(pipeline_json: dict, node_id: str) -> dict:
    """Run the pipeline up to node_id and return THAT node's output so you can
    learn the data shape: {status, rows, columns, sample (<=3 rows), error}.
    Use this on a source node before wiring downstream — if rows=0, fix params
    (e.g. widen time_range) before continuing."""
    async with httpx.AsyncClient() as c:
        r = await _post(c, f"{SIDECAR}/internal/pipeline/preview", _SH,
                        {"pipeline_json": pipeline_json, "node_id": node_id, "sample_size": 3}, 120)
    nr = r.get("node_result") or {}
    data = (nr.get("preview") or {}).get("data") or {}
    sample = data.get("rows_sample") or data.get("rows") or []
    # all_columns is the FULL name list; `columns` is capped (~30) for sample
    # economy, so newly-added columns at the tail (e.g. a time_bucket appended to
    # a 30-col flat table) get cut off. Read all_columns so cowork sees them.
    cols = data.get("all_columns") or data.get("columns") or []
    return {"status": nr.get("status"), "rows": nr.get("rows"),
            "columns": cols[:120],
            "sample": sample[:3], "error": nr.get("error")}


@mcp.tool()
async def execute(pipeline_json: dict) -> dict:
    """Run the WHOLE pipeline. Returns {status, node_results, charts, message}.
    Charts are summarized (type/title/point_count); confirm status=success and a
    chart/table came out before saving."""
    async with httpx.AsyncClient() as c:
        r = await _post(c, f"{SIDECAR}/internal/pipeline/execute", _SH, {"pipeline_json": pipeline_json}, 180)
    nr = r.get("node_results") or {}
    summ = _parse(r.get("result_summary"))
    charts = []
    for ch in (summ.get("charts") or []):
        cs = ch.get("chart_spec") or ch
        charts.append({"type": cs.get("type"), "title": cs.get("title"),
                       "points": len(cs.get("data") or [])})
    return {"status": r.get("status"),
            "node_results": {k: {"status": v.get("status"), "rows": v.get("rows"),
                                 "error": v.get("error")} for k, v in nr.items()},
            "charts": charts,
            "data_views": [{"title": dv.get("title"), "rows": len(dv.get("rows") or [])}
                           for dv in (summ.get("data_views") or [])],
            "message": r.get("error_message")}


@mcp.tool()
async def save_pipeline(name: str, pipeline_json: dict, description: str = "") -> dict:
    """Save the pipeline as a draft so a human can review it. Returns {id, view_url,
    edit_url}. The view_url shows the DAG + the rendered chart; edit_url opens the
    visual builder. Run execute() successfully BEFORE saving."""
    body = {"name": name, "description": description or "Built via MCP",
            "pipeline_kind": "diagnostic", "pipeline_json": json.dumps(pipeline_json), "version": "1.0"}
    async with httpx.AsyncClient() as c:
        r = await _post(c, f"{JAVA}/api/v1/pipelines",
                        {"Content-Type": "application/json", "Authorization": f"Bearer {SHARED}"}, body, 60)
    d = _unwrap(r)
    pid = d.get("id")
    return {"id": pid, "name": d.get("name"),
            "view_url": f"{PUBLIC}/pipeline-view/{pid}" if pid else None,
            "edit_url": f"{PUBLIC}/admin/pipeline-builder/{pid}" if pid else None}


# Auto-check Rule tool group (skill-document CRUD + two-phase confirm)
import rules  # noqa: E402
rules.register(mcp, java=JAVA, shared=SHARED, jit=JIT, public=PUBLIC)

# ASGI app for uvicorn (streamable-HTTP transport, remote MCP)
app = mcp.streamable_http_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("MCP_HOST", "127.0.0.1"),
                port=int(os.environ.get("MCP_PORT", "8060")))
