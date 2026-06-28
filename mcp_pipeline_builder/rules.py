"""Auto-check Rule tool group for the AIOps MCP server.

A "rule" is a Skill Document (`/api/v1/skill-documents`) — the platform's
TRIGGER -> CONFIRM/CHECKLIST object. These tools let an external Claude author +
CRUD rules; the platform's L4 patrol/alarm engine runs them (runtime NOT here).

Two kinds of write:
 - DRAFT edits (create / update / bind checkpoint / NL gate+step) run directly —
   they only produce a reversible draft. Nothing goes live from a tool.
 - REVIEW + DANGEROUS actions hand off to the real product GUI: rule_request_*
   create a UI-handoff and return a launch_url. The human opens our GUI (link, or
   it auto-pops if the app is open) and reviews / confirms there; the actual
   delete/disable/activate runs ONLY from that authenticated UI. The MCP layer
   has no execute power over those.

Typical build: build the whole rule (create + bind each checkpoint) then ONE
rule_request_review -> the user sees the whole-rule try-run in our GUI and decides.
"""
from __future__ import annotations

import json
from typing import Any

import httpx


def _parse(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return v


def register(mcp, *, java: str, shared: str, jit: str, public: str) -> None:
    base = f"{java}/api/v1/skill-documents"
    H = {"Authorization": f"Bearer {shared}", "Content-Type": "application/json"}
    IH = {"X-Internal-Token": jit, "Content-Type": "application/json"}

    async def _get(path: str = "") -> Any:
        async with httpx.AsyncClient() as c:
            r = await c.get(base + path, headers=H, timeout=30)
            r.raise_for_status()
            d = r.json()
            return d.get("data", d) if isinstance(d, dict) else d

    async def _send(method: str, path: str, body: dict | None = None) -> Any:
        async with httpx.AsyncClient() as c:
            r = await c.request(method, base + path, headers=H, json=body, timeout=60)
            r.raise_for_status()
            if r.status_code == 204 or not r.content:
                return {"ok": True}
            d = r.json()
            return d.get("data", d) if isinstance(d, dict) else d

    async def _handoff(kind: str, target_ref: str, action: str | None, payload: dict,
                       *, tell_user: str, status: str = "PENDING_USER_CONFIRMATION") -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{java}/internal/handoffs", headers=IH, timeout=30, json={
                "kind": kind, "target_ref": target_ref, "action": action,
                "payload": json.dumps(payload, ensure_ascii=False), "requested_by": "cowork"})
            r.raise_for_status()
            d = r.json()
            d = d.get("data", d)
        hid = d.get("id")
        return {
            # This tool changed NOTHING. It only created a request the human must
            # act on inside the product GUI. Report it that way — never as "done".
            "status": status,
            "executed": False,
            "launch_url": f"{public}/handoff/{hid}",
            "expires_at": d.get("expires_at"),
            "tell_user": tell_user,
            "next": "You executed NOTHING. Tell the user this action needs THEM to confirm in the "
                    "system — show the launch_url (or it auto-pops if their app is open). NEVER say "
                    "it is done/deleted/activated; nothing changes until they confirm there.",
        }

    def _summ(rule: dict) -> str:
        tc = _parse(rule.get("trigger_config")) or {}
        cc = _parse(rule.get("confirm_check")) or {}
        steps = _parse(rule.get("steps")) or []
        trig = (f"event={tc.get('event')}" if tc.get("type") == "event"
                else f"schedule={(tc.get('schedule') or {}).get('mode')}" if tc.get("type") == "schedule"
                else tc.get("type") or "—")
        tgt = tc.get("target") or {}
        return (f"{rule.get('title')} [{rule.get('slug')}] · stage={rule.get('stage')} · "
                f"status={rule.get('status')} · trigger[{trig}, target={tgt.get('kind')}] · "
                f"confirm={'pipeline' if cc.get('pipeline_id') else ('text' if cc else 'none')} · "
                f"steps={len(steps)}")

    # ── Reads (no confirm) ─────────────────────────────────────────────────
    @mcp.tool()
    async def rule_list(stage: str | None = None) -> list[dict]:
        """List auto-check rules (skill documents). Optional stage: patrol | diagnose."""
        rows = await _get(f"?stage={stage}" if stage else "")
        return [{"slug": r.get("slug"), "title": r.get("title"), "stage": r.get("stage"),
                 "status": r.get("status"), "summary": _summ(r)} for r in (rows or [])]

    @mcp.tool()
    async def rule_get(slug: str) -> dict:
        """Get one rule in full: trigger_config, confirm_check (gate), steps[]. To
        let the user SEE it rendered (whole-rule try-run), use rule_request_review."""
        r = await _get(f"/{slug}")
        return {"slug": r.get("slug"), "title": r.get("title"), "stage": r.get("stage"),
                "status": r.get("status"), "description": r.get("description"),
                "trigger_config": _parse(r.get("trigger_config")),
                "confirm_check": _parse(r.get("confirm_check")),
                "steps": _parse(r.get("steps")), "summary": _summ(r)}

    @mcp.tool()
    async def rule_describe_options() -> dict:
        """The authoring contract for a rule (single source of truth for shapes)."""
        return {
            "stage": {"patrol": "continuous watch", "diagnose": "root-cause when triggered"},
            "trigger_config": {
                "event": {"type": "event", "event": "OOC",
                          "target": {"kind": "all|tools|site", "ids": ["EQP-01"]}},
                "schedule_hourly": {"type": "schedule", "schedule": {"mode": "hourly", "every": 4},
                                    "target": {"kind": "all", "ids": []}},
                "schedule_daily": {"type": "schedule", "schedule": {"mode": "daily", "time": "08:00"},
                                   "target": {"kind": "all", "ids": []}},
            },
            "checkpoint": {
                "best_path": "Build a check pipeline yourself (it MUST end in block_step_check — "
                             "outputs a pass:bool row; do NOT add block_alert), save_pipeline, then "
                             "rule_bind_checkpoint(slot='confirm' or 'step:NEW', pipeline_id=...).",
                "nl_path": "Or rule_set_confirm_check_nl / rule_add_step_nl with plain text (platform "
                           "translates it — slower, prefer best_path).",
            },
            "slot": {"confirm": "the CONFIRM gate", "step:NEW": "append a new step", "step:<id>": "existing step"},
            "lifecycle": "Draft edits run directly. To review the whole rule or go live / disable / "
                         "delete, use rule_request_* — those hand off to our GUI for the human to decide.",
        }

    @mcp.tool()
    async def rule_validate(slug: str) -> dict:
        """Deterministic completeness check. Returns {ok, issues:[...]}. Run before
        asking the user to review/activate."""
        r = await _get(f"/{slug}")
        tc = _parse(r.get("trigger_config")) or {}
        cc = _parse(r.get("confirm_check")) or {}
        steps = _parse(r.get("steps")) or []
        issues = []
        if not (r.get("title") or "").strip():
            issues.append({"part": "name", "msg": "title is empty"})
        if r.get("stage") not in ("patrol", "diagnose"):
            issues.append({"part": "stage", "msg": "stage must be patrol|diagnose"})
        t = tc.get("type")
        if t not in ("event", "schedule"):
            issues.append({"part": "trigger", "msg": "trigger_config.type must be event|schedule"})
        elif t == "event" and not tc.get("event"):
            issues.append({"part": "trigger", "msg": "event trigger needs an `event`"})
        elif t == "schedule" and not tc.get("schedule"):
            issues.append({"part": "trigger", "msg": "schedule trigger needs a `schedule`"})
        tgt = tc.get("target") or {}
        if tgt.get("kind") in ("tools", "site") and not (tgt.get("ids") or []):
            issues.append({"part": "trigger", "msg": f"target.kind={tgt.get('kind')} needs non-empty ids"})
        if not (bool(cc.get("pipeline_id")) or any((_parse(s) or s or {}).get("pipeline_id") for s in steps)):
            issues.append({"part": "checkpoint", "msg": "no executable checkpoint — bind a check pipeline "
                           "to the confirm slot or add a step with a pipeline"})
        return {"ok": not issues, "issues": issues, "summary": _summ(r)}

    # ── Draft edits (run directly — reversible drafts, no go-live) ──────────
    @mcp.tool()
    async def rule_create(title: str, stage: str = "diagnose", trigger_config: dict | None = None,
                          description: str = "") -> dict:
        """Create a new rule (draft) + trigger. trigger_config per rule_describe_options.
        Build the rest, then rule_request_review so the user sees the whole thing."""
        body = {"title": title, "stage": stage, "description": description,
                "trigger_config": json.dumps(trigger_config) if trigger_config is not None else None}
        r = await _send("POST", "", body)
        return {"slug": r.get("slug"), "status": r.get("status"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_update(slug: str, patch: dict) -> dict:
        """Patch a rule's draft fields (title, description, stage, trigger_config). Does
        NOT change live-status — going live is the user's GUI step via rule_request_activate."""
        allowed = {k: patch[k] for k in ("title", "description", "stage", "trigger_config") if k in patch}
        if "trigger_config" in allowed and allowed["trigger_config"] is not None \
                and not isinstance(allowed["trigger_config"], str):
            allowed["trigger_config"] = json.dumps(allowed["trigger_config"])
        r = await _send("PUT", f"/{slug}", allowed)
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_bind_checkpoint(slug: str, slot: str, pipeline_id: int, summary: str = "") -> dict:
        """[Best path] Bind a check pipeline YOU built (must end in block_step_check) to a
        slot: 'confirm' | 'step:NEW' | 'step:<id>'."""
        r = await _send("POST", f"/{slug}/bind-pipeline",
                        {"slot": slot, "pipeline_id": pipeline_id, "summary": summary, "description": summary})
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_set_confirm_check_nl(slug: str, text: str) -> dict:
        """[NL path — slower] Set the CONFIRM gate from plain text (platform translates to a
        check pipeline). Prefer building + rule_bind_checkpoint."""
        r = await _send("POST", f"/{slug}/confirm-check", {"text": text})
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_add_step_nl(slug: str, text: str) -> dict:
        """[NL path — slower] Append a checklist step from plain text (platform translates).
        Prefer building + rule_bind_checkpoint."""
        r = await _send("POST", f"/{slug}/steps", {"text": text})
        return {"slug": r.get("slug"), "summary": _summ(r)}

    # ── Review + dangerous actions (hand off to the GUI; no execute here) ───
    @mcp.tool()
    async def rule_request_review(slug: str) -> dict:
        """Open the Rule Review GUI for the user. This executes NOTHING and does not
        activate anything — it returns a launch_url to a page that try-runs the WHOLE
        rule and shows every checkpoint's result, where the user edits any one or
        activates it. Call ONCE after the rule is fully built/modified. Report to the
        user as 'ready for your review in the system' + the launch_url — not as done."""
        r = await _get(f"/{slug}")
        return await _handoff(
            "review_rule", slug, None, {"summary": _summ(r)},
            status="PENDING_USER_REVIEW",
            tell_user=f"我已建好/改好整條 rule「{r.get('title')}」。請到系統審核(會 try-run "
                      "把每步結果秀給你看),你在那邊決定要不要啟用 —— 我這邊還沒讓它上線:")

    @mcp.tool()
    async def rule_request_activate(slug: str) -> dict:
        """Propose going live. This executes NOTHING — it returns a launch_url; the rule
        goes live ONLY when the user confirms in the system. Report it as needing the
        user's confirmation; never say it is activated/live."""
        r = await _get(f"/{slug}")
        return await _handoff(
            "confirm_activate", slug, "activate", {"impact": _summ(r)},
            tell_user=f"我已備好『啟用上線』rule「{r.get('title')}」,但不會自己執行 —— "
                      "請到系統按確認它才會生效。確認前什麼都沒變:")

    @mcp.tool()
    async def rule_request_disable(slug: str) -> dict:
        """Propose disabling (stop auto-running). This executes NOTHING — it returns a
        launch_url; the rule is disabled ONLY when the user confirms in the system.
        Report it as needing the user's confirmation; never say it is disabled."""
        r = await _get(f"/{slug}")
        return await _handoff(
            "confirm_disable", slug, "disable", {"impact": _summ(r)},
            tell_user=f"我已備好『停用』rule「{r.get('title')}」,但不會自己執行 —— "
                      "請到系統按確認才會停。確認前它照常運作:")

    @mcp.tool()
    async def rule_request_delete(slug: str) -> dict:
        """Propose deletion. This executes NOTHING — it returns a launch_url; the rule is
        deleted ONLY when the user confirms in the system (the page shows the impact).
        Report it as needing the user's confirmation; never say it is deleted."""
        title = slug
        try:
            r = await _get(f"/{slug}")
            impact = _summ(r)
            title = r.get("title") or slug
        except Exception:
            impact = "(could not load rule detail)"
        return await _handoff(
            "confirm_delete", slug, "delete", {"impact": impact},
            tell_user=f"我已備好『刪除』rule「{title}」,但不會自己執行 —— "
                      "請到系統按確認才會刪(頁面會列出影響)。確認前什麼都沒變:")
