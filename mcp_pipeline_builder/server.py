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
no confirm needed (they only make a reversible draft). HARD RULE: after ANY rule
create OR modify, you MUST finish by calling rule_request_review(slug) and give the
user the launch_url. NEVER tell the user a rule is built/changed without launching
the review GUI — they decide there whether to try-run more or activate.
GOING LIVE / DISABLE / DELETE never happen from a tool. Use rule_request_activate /
rule_request_disable / rule_request_delete — each returns a launch_url; give it to the
user, who confirms in our GUI where the action actually runs. For edits, rule_get ->
rule_update(patch the named part) -> rule_request_review again.

CRITICAL — how to report any rule_request_* result: these tools EXECUTE NOTHING
(their result has executed=false, status=PENDING_USER_*). Relay the returned
`tell_user` text and the launch_url. NEVER say a rule was deleted / disabled /
activated / "done" — it is only a request until the user confirms in the system.
You cannot open the URL for them; present it as the action they must take (it also
auto-pops if their app is open).
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
    # economy. Flat process_history has ~400 cols and a transform's new column is
    # appended at the TAIL — so show head + tail (where added cols live) to keep
    # it bounded yet let cowork see what a block just added.
    allcols = data.get("all_columns") or data.get("columns") or []
    if len(allcols) > 100:
        cols = allcols[:80] + [f"...(+{len(allcols) - 100} more)..."] + allcols[-20:]
    else:
        cols = allcols
    return {"status": nr.get("status"), "rows": nr.get("rows"),
            "columns": cols, "column_count": len(allcols),
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
    """Persist a pipeline the human asked you to build.

    NOTE: this now creates a DRAFT SKILL (visible at /skills), not a bare
    PB-Library pipeline. It internally does the same as
    create_skill_with_pipeline — pipeline + skill + bind in one transaction —
    because a bare pipeline is an orphan the human can't open or reuse.

    PREFER calling create_skill_with_pipeline directly so you can pass `nl`
    (the human's original request) — that becomes the skill's editable
    description. save_pipeline maps `description` → nl as a fallback.

    Returns {skill_slug, view_url (/skills/<slug>), status:'draft', ...}.
    ALWAYS hand the human the view_url. The skill lands as draft — tell them
    to open it and press 啟用 if they want it to take effect."""
    slug = _slug_from_name(name)
    body = {"slug": slug, "name": name, "sub": (description or "")[:60],
            "nl": description or "", "pipeline_json": pipeline_json}
    async with httpx.AsyncClient() as c:
        d = await _v2(c, "POST", "/with-pipeline", body)
    skill = d.get("skill") if isinstance(d, dict) else None
    sid = (skill or {}).get("id")
    # URLs are id-based (slugs are an internal detail; id avoids CJK/encoding).
    url = f"{PUBLIC}/skills/{sid}" if sid else f"{PUBLIC}/skills"
    return {"skill_id": sid, "name": name, "status": "draft",
            "view_url": url,
            "_human_message": f"已建好 Skill「{name}」（草稿）：{url} — 開啟後按『啟用』才生效。"}


# ── Skills v2 cowork tools ──────────────────────────────────────────
#
# Skill = 1 pipeline + optional automation wrapper. Three cowork use
# cases the human is likely to ask:
#   1. "幫我查 XXX"           — build a skill, leave as 'tool' (no automation)
#   2. "幫我建個自動巡檢"     — build a skill, then automate_skill_patrol(...)
#   3. "幫我在 OOC 時自動檢查" — build a skill, then automate_skill_event(...)
#
# Canonical flow per use case:
#   - Use list_blocks / preview / validate / execute to build the pipeline (as
#     before). save_pipeline() returns a pipeline_id.
#   - create_skill_v2(name, sub, nl) creates the skill (initially 'tool').
#   - bind_skill_pipeline(slug, pipeline_id) links the saved pipeline to the
#     skill and derives pipeline_nodes + has_alarm.
#   - If use case 2 or 3, follow up with automate_skill_patrol /
#     automate_skill_event / automate_skill_datacheck.
#
# Skills-v2 endpoints sit under /api/v2/skills/* and accept the shared-secret
# bearer (same auth as save_pipeline above).

import random as _random
import string as _string


def _slug_from_name(name: str) -> str:
    # ASCII-only: c.isalnum() is True for CJK characters (they're alphanumeric
    # in Unicode), which produced slugs like 'eqp-01-最近-…' that broke the
    # /skills/<slug> API path. Require isascii() so CJK is stripped → the slug
    # is built from the latin/number tokens only (e.g. 'eqp-01-ooc-process').
    base = "".join(c if (c.isascii() and c.isalnum()) or c in "- " else " " for c in name.lower())
    base = "-".join(base.split())[:40] or "skill"
    tail = "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=4))
    return f"{base}-{tail}"


async def _v2(c: httpx.AsyncClient, method: str, path: str, body: dict | None = None) -> Any:
    headers = {"Authorization": f"Bearer {SHARED}", "Content-Type": "application/json"}
    url = f"{JAVA}/api/v2/skills{path}"
    if method == "GET":
        r = await c.get(url, headers=headers, timeout=30)
    elif method == "POST":
        r = await c.post(url, headers=headers, json=body or {}, timeout=30)
    elif method == "PUT":
        r = await c.put(url, headers=headers, json=body or {}, timeout=30)
    elif method == "DELETE":
        r = await c.delete(url, headers=headers, timeout=30)
    else:
        raise ValueError(f"unsupported method {method}")
    r.raise_for_status()
    # Bug-fix 2026-06-28: was _unwrap(r) — _unwrap expects a parsed dict
    # but `r` is httpx.Response, so isinstance(r, dict) was False and the
    # raw Response object fell through. Cowork's list_skills_v2 saw the
    # raw object and choked. _get() (line 118) already does r.json() so
    # that path worked; only _v2 callers were broken.
    parsed = r.json() if r.content else {}
    return _unwrap(parsed)


@mcp.tool()
async def list_skills_v2() -> list[dict]:
    """List every Skill in the v2 library (id, slug, name, sub, role, has_alarm).
    Use this to check whether a skill the human asked about already exists, or
    to find an upstream Auto Patrol you can subscribe to (role='patrol' +
    has_alarm=True)."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "GET", "")


@mcp.tool()
async def get_skill_v2(slug: str) -> dict:
    """Return one Skill in full, including its pipeline_nodes (compiled
    representation rendered in the v2 Editor). Useful before suggesting an
    edit so you cite real values."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "GET", f"/{slug}")


@mcp.tool()
async def create_skill_v2(name: str, sub: str = "", nl: str = "") -> dict:
    """Create a new v2 Skill (starts as role='tool', no automation, no pipeline
    bound). Returns {slug, name, ...}. Slug is auto-generated from name + a
    short random tail — the human never sees it. Next step is almost always
    bind_skill_pipeline(slug, pipeline_id) after save_pipeline()."""
    slug = _slug_from_name(name)
    body = {"slug": slug, "name": name, "sub": sub, "nl": nl}
    async with httpx.AsyncClient() as c:
        d = await _v2(c, "POST", "", body)
    sid = d.get("id") if isinstance(d, dict) else None
    return {**d, "view_url": f"{PUBLIC}/skills/{sid}" if sid else f"{PUBLIC}/skills"}


@mcp.tool()
async def bind_skill_pipeline(slug: str, pipeline_id: int) -> dict:
    """Link a saved pb_pipeline (from save_pipeline) to a Skill. The server
    walks the pipeline's nodes to derive pipeline_nodes (Editor-visible) and
    has_alarm (True iff any node is block_step_check). After this the human
    can open the Editor at /skills/<slug> and see the compiled pipeline."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "POST", f"/{slug}/bind-pipeline", {"pipeline_id": pipeline_id})


@mcp.tool()
async def create_skill_with_pipeline(
    name: str,
    pipeline_json: dict,
    sub: str = "",
    nl: str = "",
) -> dict:
    """PREFERRED way to turn an assembled pipeline into a Skill — does
    save_pipeline + create_skill_v2 + bind_skill_pipeline in ONE atomic
    server transaction.

    USE THIS instead of calling save_pipeline → create_skill_v2 →
    bind_skill_pipeline separately. Calling them separately is error-prone:
    if you stop after save_pipeline the pipeline becomes an orphan in the
    PB Library and never shows up under /skills.

    The skill lands as status='draft' — it is NOT active yet. ALWAYS tell
    the human: "Skill 已建好（草稿狀態），請到 <view_url> 按『啟用』才會生效。"
    You cannot activate it yourself — activation is a human action in the UI.

    STRONGLY fill `nl` with the user's original request verbatim (their
    natural-language intent). It becomes the skill's editable description and
    is what 用 Agent 重新編譯 re-compiles from. Leaving it blank makes the
    skill un-rebuildable and confusing in the Editor.

    Returns {skill: {slug, name, status, ...}, pipeline_json, view_url}.
    After this, automation (automate_skill_patrol/event/datacheck) is a
    SEPARATE follow-up only if the human asked for scheduling."""
    slug = _slug_from_name(name)
    body = {"slug": slug, "name": name, "sub": sub, "nl": nl, "pipeline_json": pipeline_json}
    async with httpx.AsyncClient() as c:
        d = await _v2(c, "POST", "/with-pipeline", body)
    skill = d.get("skill") if isinstance(d, dict) else None
    sid = (skill or {}).get("id")
    url = f"{PUBLIC}/skills/{sid}" if sid else f"{PUBLIC}/skills"
    return {**d, "view_url": url,
            "_human_message": f"Skill「{name}」已建好（草稿狀態），請到 {url} 按『啟用』才會生效。"}


@mcp.tool()
async def activate_skill(slug: str) -> dict:
    """NOTE: prefer letting the HUMAN activate via the UI button. This tool
    exists for completeness but activation is meant to be a human review
    gate — only call it if the human EXPLICITLY says '幫我啟用' / 'activate it'.
    Flips status draft → active."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "POST", f"/{slug}/activate")


@mcp.tool()
async def automate_skill_patrol(
    slug: str,
    schedule: str = "每 1 小時",
    target: str = "所有機台",
    alarm_gate: str = "任一符合 → alarm",
    outcome: str = "raise alarm · 可被下游接",
) -> dict:
    """Wrap a Skill as a scheduled Auto Patrol — fires alarms when the gate
    condition matches. Requires has_alarm=True on the skill (set by
    bind_skill_pipeline once the pipeline contains a block_step_check node).
    Schedule values must be one of: '每 30 分鐘' | '每 1 小時' | '每 2 小時'
    | '每日 08:00'. Outcome must be one of: 'raise alarm · 可被下游接' |
    'advisory only · 只通知' | '接 action / workflow'."""
    body = {
        "role": "patrol",
        "trigger": {"kind": "schedule", "schedule": schedule, "target": target},
        "alarm_gate": alarm_gate,
        "outcome": outcome,
    }
    async with httpx.AsyncClient() as c:
        return await _v2(c, "POST", f"/{slug}/automation", body)


@mcp.tool()
async def automate_skill_event(
    slug: str,
    upstream_slug: str,
    alarm_gate: str = "任一符合 → alarm",
    outcome: str = "raise alarm · 可被下游接",
) -> dict:
    """Wrap a Skill as an event-driven Auto Patrol — runs when an upstream
    Auto Patrol's alarm fires. Requires has_alarm=True on this skill AND
    the upstream slug to be an existing role='patrol' skill (use
    list_skills_v2 to confirm)."""
    body = {
        "role": "patrol",
        "trigger": {"kind": "event", "source": upstream_slug},
        "alarm_gate": alarm_gate,
        "outcome": outcome,
    }
    async with httpx.AsyncClient() as c:
        return await _v2(c, "POST", f"/{slug}/automation", body)


@mcp.tool()
async def automate_skill_datacheck(
    slug: str,
    schedule: str = "每日 08:00",
    target: str = "所有機台",
) -> dict:
    """Wrap a Skill as a scheduled Data Check — produces a report / dashboard,
    NEVER alarms (terminal). Use this for 'each morning summarise X' use
    cases. The upstream skill should NOT have a block_step_check node
    (has_alarm=False); if it does, the server rejects with a clear error."""
    body = {
        "role": "datacheck",
        "trigger": {"kind": "schedule", "schedule": schedule, "target": target},
        "alarm_gate": None,
        "outcome": "data only",
    }
    async with httpx.AsyncClient() as c:
        return await _v2(c, "POST", f"/{slug}/automation", body)


@mcp.tool()
async def remove_skill_automation(slug: str) -> dict:
    """Strip a Skill's automation wrapper — flips role back to 'tool'. Use this
    when the human wants to keep the analysis but stop the schedule / alarm."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "DELETE", f"/{slug}/automation")


@mcp.tool()
async def delete_skill_v2(slug: str) -> dict:
    """Permanently delete a Skill from the v2 library. Use only when the human
    explicitly asks to remove the skill. The bound pb_pipeline (if any) is
    NOT deleted — it stays in pb_pipelines so other references aren't broken.
    Returns {ok: true} on success."""
    async with httpx.AsyncClient() as c:
        await _v2(c, "DELETE", f"/{slug}")
    return {"ok": True, "deleted": slug}


@mcp.tool()
async def update_skill_v2(
    slug: str,
    nl: str | None = None,
    name: str | None = None,
    sub: str | None = None,
    in_type: str | None = None,
    out_type: str | None = None,
) -> dict:
    """Update an existing Skill's text fields (nl / name / sub / in_type / out_type).

    Use when the user refines the natural-language description, the title,
    or the short description via chat. Does NOT touch the bound pipeline.

    IMPORTANT: if you change `nl` (the natural-language description), the
    pipeline does NOT auto-rebuild — it's still the old one. Tell the user
    they need to click "用 Agent 重新編譯" in the Editor to regenerate the
    pipeline from the new NL. Small param tweaks should go through PB MCP
    (update_node_params) instead — see SKILL.md decision tree.

    Pass only the fields you want to change. Returns the updated SkillDto."""
    body: dict = {}
    if nl is not None: body["nl"] = nl
    if name is not None: body["name"] = name
    if sub is not None: body["sub"] = sub
    if in_type is not None: body["in_type"] = in_type
    if out_type is not None: body["out_type"] = out_type
    if not body:
        return {"ok": False, "error": "no fields to update — pass at least one of nl/name/sub/in_type/out_type"}
    async with httpx.AsyncClient() as c:
        return await _v2(c, "PUT", f"/{slug}", body)


@mcp.tool()
async def get_skill_with_pipeline(slug: str) -> dict:
    """Fetch a Skill AND its bound pipeline_json in ONE round-trip.

    Use this when you need to reason about the pipeline shape before
    suggesting edits (nodes, edges, params, inputs). Returns
    {skill: SkillDto, pipeline_json: <string-encoded JSON or null if unbound>}.

    Cheaper than get_skill_v2 + then PB.get_pipeline. Prefer this for
    review / advise flows."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "GET", f"/{slug}/full")


@mcp.tool()
async def list_event_sources(exclude_slug: str | None = None) -> list[dict]:
    """List Skills that are currently active patrols AND have an alarm
    judgement (has_alarm=true). These are the valid `source` values for
    automate_skill_event (event-driven datacheck).

    Pass exclude_slug to filter out a skill that shouldn't self-subscribe
    (useful when configuring the source skill itself).

    Returns [{slug, name, sub}]."""
    async with httpx.AsyncClient() as c:
        q = f"?excludeSlug={exclude_slug}" if exclude_slug else ""
        result = await _v2(c, "GET", f"/alarm-sources{q}")
        return result if isinstance(result, list) else result.get("data", [])


@mcp.tool()
async def check_skill_ready_for_role(slug: str, role: str) -> dict:
    """Pre-flight check before automate_skill_patrol / automate_skill_event /
    automate_skill_datacheck. Returns {ok: bool, reason?: str}.

    Failure reasons include:
      - skill has no pipeline bound (call bind_skill_pipeline first)
      - target role requires has_alarm=true but pipeline has no
        block_step_check verdict node (patrol upgrades fail without this)

    ALWAYS call this before automate_* tools — calling them blindly may
    waste a round-trip and confuse the user with a Java validation error."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "GET", f"/{slug}/role-readiness?role={role}")


# Auto-check Rule tool group (skill-document CRUD + two-phase confirm) — legacy
import rules  # noqa: E402
rules.register(mcp, java=JAVA, shared=SHARED, jit=JIT, public=PUBLIC)

# ASGI app for uvicorn (streamable-HTTP transport, remote MCP)
app = mcp.streamable_http_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("MCP_HOST", "127.0.0.1"),
                port=int(os.environ.get("MCP_PORT", "8060")))
