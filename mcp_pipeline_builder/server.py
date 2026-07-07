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


async def _handoff(kind: str, target_ref: str, action: str, payload: dict,
                   *, tell_user: str) -> dict:
    """Create a UI-handoff for a CRITICAL action instead of executing it.
    cowork proposes; the human confirms in the authed GUI (HandoffService.resolve
    runs the real action under their auth). Returns a launch_url — NOT a result.
    Mirrors rules.py._handoff (same /internal/handoffs endpoint)."""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{JAVA}/internal/handoffs", headers=_JH, timeout=30, json={
            "kind": kind, "target_ref": target_ref, "action": action,
            "payload": json.dumps(payload, ensure_ascii=False), "requested_by": "cowork"})
        r.raise_for_status()
        d = r.json()
        d = d.get("data", d)
    hid = d.get("id")
    return {
        "status": "PENDING_USER_CONFIRMATION",
        "executed": False,
        "launch_url": f"{PUBLIC}/handoff/{hid}",
        "expires_at": d.get("expires_at"),
        "tell_user": tell_user,
        "_next": "你什麼都沒做。把 launch_url 給 user，請他在系統裡確認才會執行。"
                 "絕不要說已刪除/已啟用/已設定 —— 在他確認前什麼都沒變。",
    }


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
    """Request linking a pb_pipeline to a Skill. CRITICAL (overwrites any
    existing binding → can destroy the user's current pipeline) → this does NOT
    bind. It creates a confirmation request; the human confirms in the GUI via
    the returned launch_url. Report it as 'needs your confirmation'; never say
    it was bound."""
    return await _handoff("confirm_skill_bind", slug, "bind_skill_pipeline",
                          {"slug": slug, "pipeline_id": pipeline_id},
                          tell_user=f"要把 pipeline {pipeline_id} 綁到 Skill「{slug}」嗎？"
                                    f"會覆蓋目前綁定。請開連結確認。")


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
    """Request activating a Skill (draft → active = it goes LIVE and starts
    running automatically). CRITICAL → this does NOT activate. It creates a
    confirmation request; the human confirms in the GUI via the launch_url
    (or just presses 啟用 in the Editor). Never say it was activated."""
    return await _handoff("confirm_skill_activate", slug, "activate_skill", {"slug": slug},
                          tell_user=f"要啟用 Skill「{slug}」嗎？啟用後它會自動開始運作。請開連結確認。")


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
    'advisory only · 只通知' | '接 action / workflow'.
    CRITICAL (sets the skill to fire automatically + raise alarms) → this does
    NOT apply. It creates a confirmation request; the human confirms in the GUI
    via the launch_url. Never say automation was set up."""
    body = {
        "role": "patrol",
        "trigger": {"kind": "schedule", "schedule": schedule, "target": target},
        "alarm_gate": alarm_gate,
        "outcome": outcome,
    }
    return await _handoff("confirm_skill_automate", slug, "automate_skill", body,
                          tell_user=f"要把 Skill「{slug}」設成 Auto Patrol（{schedule}、{target}、達標發 alarm）嗎？請開連結確認。")


@mcp.tool()
async def automate_skill_event(
    slug: str,
    upstream_slug: str,
    alarm_gate: str = "任一符合 → alarm",
    outcome: str = "raise alarm · 可被下游接",
) -> dict:
    """Wrap a Skill as an event-driven Auto Patrol — runs when an upstream
    Auto Patrol's alarm fires. Requires has_alarm=True + upstream a role='patrol'.
    CRITICAL → this does NOT apply; it creates a confirmation request for the
    human to confirm in the GUI via the launch_url. Never say it was set up."""
    body = {
        "role": "patrol",
        "trigger": {"kind": "event", "source": upstream_slug},
        "alarm_gate": alarm_gate,
        "outcome": outcome,
    }
    return await _handoff("confirm_skill_automate", slug, "automate_skill", body,
                          tell_user=f"要把 Skill「{slug}」設成事件觸發（上游 {upstream_slug} 發 alarm 時跑）嗎？請開連結確認。")


@mcp.tool()
async def automate_skill_datacheck(
    slug: str,
    schedule: str = "每日 08:00",
    target: str = "所有機台",
) -> dict:
    """Wrap a Skill as a scheduled Data Check — produces a report / dashboard,
    NEVER alarms (terminal). Use this for 'each morning summarise X' use cases.
    CRITICAL → this does NOT apply; it creates a confirmation request for the
    human to confirm in the GUI via the launch_url. Never say it was set up."""
    body = {
        "role": "datacheck",
        "trigger": {"kind": "schedule", "schedule": schedule, "target": target},
        "alarm_gate": None,
        "outcome": "data only",
    }
    return await _handoff("confirm_skill_automate", slug, "automate_skill", body,
                          tell_user=f"要把 Skill「{slug}」設成 Data Check（{schedule}、{target}、不發 alarm）嗎？請開連結確認。")


@mcp.tool()
async def remove_skill_automation(slug: str) -> dict:
    """Strip a Skill's automation wrapper — flips role back to 'tool'. Use this
    when the human wants to keep the analysis but stop the schedule / alarm."""
    async with httpx.AsyncClient() as c:
        return await _v2(c, "DELETE", f"/{slug}/automation")


@mcp.tool()
async def delete_skill_v2(slug: str) -> dict:
    """Request permanent deletion of a Skill. CRITICAL + IRREVERSIBLE → this does
    NOT delete. It creates a confirmation request; the human must open the
    returned launch_url and confirm in the GUI before anything is removed.
    Report it as 'needs your confirmation', show the launch_url, and NEVER say
    the skill was deleted."""
    return await _handoff("confirm_skill_delete", slug, "delete_skill_v2", {"slug": slug},
                          tell_user=f"要刪除 Skill「{slug}」嗎？這不可復原。請開連結確認。")


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


# ── 真 Skill 化 + 治理提案 (cowork 開放, 2026-07-08) ─────────────────────────

# 與 sidecar coordinator_triage.apply_presentation_patch 同語意的內聯副本 —
# MCP venv 只有 mcp+httpx，不能 import sidecar；白名單改動時兩邊要同步。
_CHART_BLOCKS = {
    "block_line_chart", "block_bar_chart", "block_xbar_r", "block_imr",
    "block_spc_panel", "block_apc_panel", "block_box_plot",
    "block_scatter_chart", "block_histogram_chart", "block_pareto",
    "block_probability_plot", "block_ewma_cusum", "block_data_view",
}
_PATCHABLE = {
    "style", "tooltip_fields", "weco_annotate", "title", "order",
    "show_values", "y_label", "x_label", "line_style", "show_markers",
    "marker_size", "spc_zones", "legend", "series_field", "max_rows",
}


def _apply_presentation_patch(pj: dict, patch: list) -> tuple[dict | None, str]:
    if not isinstance(patch, list) or not patch:
        return None, "empty patch"
    nodes = {str(n.get("id")): n for n in (pj.get("nodes") or [])}
    out = json.loads(json.dumps(pj))
    out_nodes = {str(n.get("id")): n for n in (out.get("nodes") or [])}
    touched = 0
    for item in patch:
        if not isinstance(item, dict):
            return None, "patch item is not an object"
        nid = str(item.get("node") or "")
        sets = item.get("set")
        if nid not in nodes:
            return None, f"unknown node '{nid}'"
        if nodes[nid].get("block_id") not in _CHART_BLOCKS:
            return None, f"node '{nid}' is not a chart block"
        if not isinstance(sets, dict) or not sets:
            return None, f"node '{nid}' patch has no set object"
        illegal = [k for k in sets if k not in _PATCHABLE]
        if illegal:
            return None, f"params {illegal} not presentation-patchable"
        params = dict(out_nodes[nid].get("params") or {})
        for k, v in sets.items():
            if k == "style" and isinstance(v, dict) and isinstance(params.get("style"), dict):
                params["style"] = {**params["style"], **v}
            else:
                params[k] = v
        out_nodes[nid]["params"] = params
        touched += 1
    if touched == 0:
        return None, "patch touched nothing"
    return out, ""



@mcp.tool()
async def parameterize_pipeline(pipeline_json: dict, accept: list[str] | None = None) -> dict:
    """把 pipeline 寫死的 source 身分參數（tool_id/step/time_range/limit…）升級成
    可帶參數的 inputs（$name）。不帶 accept → 回候選清單（含建議名稱與預設值）；
    帶 accept（候選名稱清單）→ 回參數化後的 pipeline_json。
    典型流程：build → parameterize_pipeline(pj) 看候選 → parameterize_pipeline(pj,
    accept=[...]) → 用回傳的 pipeline_json 走 create_skill_with_pipeline。
    完全確定性 — 不會動資料結構，只把具體值換成 $ 變數並加宣告。"""
    async with httpx.AsyncClient() as c:
        body: dict = {"pipeline_json": pipeline_json}
        if accept:
            body["accept"] = accept
        return await _post(c, f"{SIDECAR}/internal/pipeline/parameterize",
                           {"X-Service-Token": SVC}, body)


@mcp.tool()
async def draft_skill_doc(name: str, pipeline_json: dict, nl: str = "") -> dict:
    """為 skill 草擬說明書（use_case / when_to_use[] / distinction /
    example_invocation / tags[]）。這是「草稿」— 請把它呈現給 human 修改確認後，
    再放進 create_skill_with_pipeline 的 doc 欄位；不要未經確認直接存。"""
    async with httpx.AsyncClient() as c:
        return await _post(c, f"{SIDECAR}/internal/pipeline/skill-draft-doc",
                           {"X-Service-Token": SVC},
                           {"name": name, "nl": nl, "pipeline_json": pipeline_json},
                           timeout=60)


@mcp.tool()
async def patch_chart_style(pipeline_json: dict, patch: list[dict]) -> dict:
    """對 pipeline 的 chart 節點打「呈現層」參數 patch — 只能動樣式面：
    style:{spc_zones,line_style,show_markers,marker_size,x_label,y_label} /
    tooltip_fields / weco_annotate / title / order / show_values。
    patch 形狀：[{"node": "<chart node id>", "set": {"style": {...}, ...}}]。
    資料參數（ucl_column、x、y、tool_id…）從白名單層就擋掉 — 要改資料請重建。
    回傳 {pipeline_json} 供後續 execute / save_pipeline。"""
    patched, why = _apply_presentation_patch(pipeline_json, patch)
    if patched is None:
        return {"error": f"patch rejected: {why}",
                "hint": "只能動 chart 節點的呈現參數；節點 id 要存在"}
    return {"pipeline_json": patched}


@mcp.tool()
async def propose_knowledge(memo_class: str, title: str, body: str,
                            applies_to: str = "execute",
                            subject_kind: str | None = None,
                            subject_id: str | None = None) -> dict:
    """向平台知識庫「提案」一條 knowledge（進 Supervisor 審核佇列，人審後才生效 —
    你永遠是提案者，不能直接寫入）。memo_class 限 domain | procedure | correction。
    body 建議含 **Why:** 與 **How to apply:** 兩段。subject_kind/subject_id 標註
    這條知識關於什麼（例 block / block_line_chart）。"""
    if memo_class not in ("domain", "procedure", "correction"):
        return {"error": "memo_class 限 domain | procedure | correction（preference 不開放外部代理）"}
    async with httpx.AsyncClient() as c:
        out = await _post(c, f"{JAVA}/internal/memory/knowledge",
                          {"X-Internal-Token": JIT}, {
                              "user_id": None,
                              "memo_class": memo_class,
                              "title": title[:200],
                              "body": body[:4000],
                              "applies_to": applies_to,
                              "source": "cowork",
                              "active": False,          # 治理紅線: 草稿, 零直寫
                              "written_by": "cowork",
                              "status": "draft",
                              "subject_kind": subject_kind,
                              "subject_id": subject_id,
                          })
        d = _unwrap(out)
        return {"status": "proposed", "id": (d or {}).get("id"),
                "note": "已進審核佇列（draft）— Supervisor/PE 核准後才會生效。"}


@mcp.tool()
async def propose_doc_revision(block_id: str, revised_doc_draft: str, rationale: str) -> dict:
    """對某個 block 的官方文件提出「修訂提案」（DOC_REVISE）。提案會出現在
    Supervisor 工作台，由 IT_ADMIN 簽核後才落地 — document 是系統資產，
    你永遠是提案者。revised_doc_draft 是修訂後的段落草稿（markdown），
    rationale 說明為什麼要改（引具體證據）。"""
    async with httpx.AsyncClient() as c:
        out = await _post(c, f"{JAVA}/internal/supervisor/proposals",
                          {"X-Internal-Token": JIT}, {
                              "action_type": "DOC_REVISE",
                              "target_ids": [],
                              "proposal": json.dumps({
                                  "block_id": block_id,
                                  "revised_doc_draft": revised_doc_draft[:6000],
                              }, ensure_ascii=False),
                              "rationale": rationale[:1000],
                              "proposer_meta": {"source": "cowork", "proposer": "cowork-mcp"},
                              "narrative": json.dumps({
                                  "happened": f"cowork 對 {block_id} 文件提出修訂",
                                  "observed": rationale[:400],
                                  "action": f"以修訂草案更新 {block_id} 的 block 文件（IT_ADMIN 簽核後生效）",
                                  "subject": {"kind": "block", "id": block_id, "label": block_id},
                              }, ensure_ascii=False),
                          })
        d = _unwrap(out)
        return {"status": "proposed", "id": (d or {}).get("id"),
                "note": "DOC_REVISE 提案已建立 — 到 Supervisor 工作台由 IT_ADMIN 簽核後才會更新文件。"}


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
