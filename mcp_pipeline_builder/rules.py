"""Auto-check Rule tool group for the AIOps MCP server.

A "rule" is a Skill Document (`/api/v1/skill-documents`) — the platform's
TRIGGER -> CONFIRM -> CHECKLIST object. These tools let an external Claude
author + CRUD rules; the platform's L4 patrol/alarm engine runs them (runtime
NOT in scope here).

Every state-changing tool is TWO-PHASE: call once WITHOUT confirm_token to get a
human-readable preview + a token; call again WITH the token to commit. The token
binds to the exact payload (token == hash(action+args)), so the committed change
equals the previewed one. Reads (list/get/validate/describe) need no confirm.

Activation (go-live / status=stable) is intentionally NOT exposed — that stays a
human action in the UI. Tools only ever produce drafts or disable/delete.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import httpx

_SALT = os.environ.get("MCP_CONFIRM_SALT", "aiops-mcp-confirm-v1")
_STAGES = ("patrol", "diagnose")


def _canon(action: str, args: dict) -> str:
    return json.dumps({"action": action, "args": args}, sort_keys=True, ensure_ascii=False, default=str)


def _token(action: str, args: dict) -> str:
    return hashlib.sha256((_SALT + _canon(action, args)).encode("utf-8")).hexdigest()[:20]


def _need_confirm(action: str, args: dict, preview: str) -> dict:
    return {
        "requires_confirm": True,
        "action": action,
        "preview": preview,
        "confirm_token": _token(action, args),
        "next": "Show this preview to the user, get an explicit confirmation, then "
                "call this tool again with the SAME arguments plus confirm_token.",
    }


def _bad_token() -> dict:
    return {"error": "confirm_token mismatch or stale — re-run WITHOUT confirm_token "
                     "to get a fresh preview, then confirm again."}


def _parse(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return v


def register(mcp, *, java: str, shared: str, public: str) -> None:
    base = f"{java}/api/v1/skill-documents"
    H = {"Authorization": f"Bearer {shared}", "Content-Type": "application/json"}

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

    def _summ(rule: dict) -> str:
        tc = _parse(rule.get("trigger_config")) or {}
        cc = _parse(rule.get("confirm_check")) or {}
        steps = _parse(rule.get("steps")) or []
        trig = (f"event={tc.get('event')}" if tc.get("type") == "event"
                else f"schedule={(tc.get('schedule') or {}).get('mode')}" if tc.get("type") == "schedule"
                else tc.get("type") or "—")
        tgt = (tc.get("target") or {})
        return (f"slug={rule.get('slug')} · {rule.get('title')} · stage={rule.get('stage')} · "
                f"status={rule.get('status')} · trigger[{trig}, target={tgt.get('kind')}] · "
                f"confirm_check={'yes' if cc.get('pipeline_id') else ('text-only' if cc else 'none')} · "
                f"steps={len(steps)}")

    # ── Reads ──────────────────────────────────────────────────────────────
    @mcp.tool()
    async def rule_list(stage: str | None = None) -> list[dict]:
        """List auto-check rules (skill documents). Optional stage filter:
        patrol (continuous watch) | diagnose (root-cause when triggered).
        Returns slug/title/stage/status + a one-line trigger summary."""
        rows = await _get(f"?stage={stage}" if stage else "")
        return [{"slug": r.get("slug"), "title": r.get("title"), "stage": r.get("stage"),
                 "status": r.get("status"), "summary": _summ(r)} for r in (rows or [])]

    @mcp.tool()
    async def rule_get(slug: str) -> dict:
        """Get one rule in full: trigger_config, confirm_check (the gate), and the
        ordered steps[] (each = text + pipeline_id + suggested_actions)."""
        r = await _get(f"/{slug}")
        return {"slug": r.get("slug"), "title": r.get("title"), "stage": r.get("stage"),
                "status": r.get("status"), "description": r.get("description"),
                "trigger_config": _parse(r.get("trigger_config")),
                "confirm_check": _parse(r.get("confirm_check")),
                "steps": _parse(r.get("steps")), "summary": _summ(r)}

    @mcp.tool()
    async def rule_describe_options() -> dict:
        """The authoring contract for a rule (single source of truth for shapes).
        Use this before building trigger_config / binding checkpoints."""
        return {
            "stage": {"patrol": "continuous watch", "diagnose": "root-cause when triggered"},
            "trigger_config": {
                "event": {"type": "event", "event": "OOC (or other registry event)",
                          "target": {"kind": "all|tools|site", "ids": ["EQP-01", "..."]}},
                "schedule": {"type": "schedule",
                             "schedule": {"mode": "hourly", "every": 4},
                             "target": {"kind": "all|tools|site", "ids": []}},
                "schedule_daily": {"type": "schedule", "schedule": {"mode": "daily", "time": "08:00"},
                                   "target": {"kind": "all", "ids": []}},
            },
            "checkpoint": {
                "best_path": "Build a check pipeline yourself with the pipeline tools "
                             "(it MUST end in block_step_check, which outputs port `check` "
                             "with a pass:bool row — do NOT add block_alert), save_pipeline, "
                             "then rule_bind_checkpoint(slot='confirm' or 'step:NEW', pipeline_id=...).",
                "nl_path": "Or pass plain text to rule_set_confirm_check_nl / rule_add_step_nl "
                           "and the platform translates it (slower, lower quality — prefer best_path).",
            },
            "slot": {"confirm": "the CONFIRM gate", "step:NEW": "append a new checklist step",
                     "step:<id>": "bind to an existing step"},
            "activation": "Going live (status=stable) is a HUMAN action in the UI — not a tool.",
        }

    @mcp.tool()
    async def rule_validate(slug: str) -> dict:
        """Deterministic completeness check on a rule. Returns {ok, issues:[...]}.
        Run before telling the user a rule is ready (it still needs human go-live)."""
        r = await _get(f"/{slug}")
        tc = _parse(r.get("trigger_config")) or {}
        cc = _parse(r.get("confirm_check")) or {}
        steps = _parse(r.get("steps")) or []
        issues = []
        if not (r.get("title") or "").strip():
            issues.append({"part": "name", "msg": "title is empty"})
        if r.get("stage") not in _STAGES:
            issues.append({"part": "stage", "msg": f"stage must be one of {_STAGES}"})
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
        has_check = bool(cc.get("pipeline_id")) or any((_parse(s) or s or {}).get("pipeline_id") for s in steps)
        if not has_check:
            issues.append({"part": "checkpoint", "msg": "no executable checkpoint — bind a check "
                           "pipeline to the confirm slot or add a step with a pipeline"})
        return {"ok": not issues, "issues": issues, "summary": _summ(r)}

    # ── Writes (two-phase confirm) ─────────────────────────────────────────
    @mcp.tool()
    async def rule_create(title: str, stage: str = "diagnose", trigger_config: dict | None = None,
                          description: str = "", confirm_token: str | None = None) -> dict:
        """Create a new rule (draft). trigger_config per rule_describe_options.
        Two-phase: call without confirm_token for a preview + token, then confirm."""
        args = {"title": title, "stage": stage, "trigger_config": trigger_config, "description": description}
        if not confirm_token:
            tc = trigger_config or {}
            return _need_confirm("rule_create", args,
                f"CREATE rule (draft): '{title}' · stage={stage} · "
                f"trigger={tc.get('type')}/{tc.get('event') or (tc.get('schedule') or {}).get('mode')} · "
                f"target={(tc.get('target') or {}).get('kind')}. No checkpoint yet — bind one after.")
        if confirm_token != _token("rule_create", args):
            return _bad_token()
        body = {"title": title, "stage": stage, "description": description,
                "trigger_config": json.dumps(trigger_config) if trigger_config is not None else None}
        r = await _send("POST", "", body)
        return {"slug": r.get("slug"), "status": r.get("status"),
                "edit_url": f"{public}/skills/{r.get('slug')}", "summary": _summ(r)}

    @mcp.tool()
    async def rule_update(slug: str, patch: dict, confirm_token: str | None = None) -> dict:
        """Patch a rule (draft fields: title, description, stage, trigger_config).
        Does NOT change live-status. Two-phase confirm."""
        allowed = {k: patch[k] for k in ("title", "description", "stage", "trigger_config") if k in patch}
        args = {"slug": slug, "patch": allowed}
        if not confirm_token:
            return _need_confirm("rule_update", args, f"UPDATE rule {slug}: set {list(allowed.keys())}.")
        if confirm_token != _token("rule_update", args):
            return _bad_token()
        body = dict(allowed)
        if "trigger_config" in body and body["trigger_config"] is not None and not isinstance(body["trigger_config"], str):
            body["trigger_config"] = json.dumps(body["trigger_config"])
        r = await _send("PUT", f"/{slug}", body)
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_bind_checkpoint(slug: str, slot: str, pipeline_id: int, summary: str = "",
                                   confirm_token: str | None = None) -> dict:
        """[Best path] Bind a check pipeline YOU built (must end in block_step_check)
        to a slot: 'confirm' (the gate) | 'step:NEW' | 'step:<id>'. Two-phase confirm."""
        args = {"slug": slug, "slot": slot, "pipeline_id": pipeline_id, "summary": summary}
        if not confirm_token:
            return _need_confirm("rule_bind_checkpoint", args,
                f"BIND pipeline #{pipeline_id} to rule {slug} slot '{slot}'. ({summary or 'no summary'})")
        if confirm_token != _token("rule_bind_checkpoint", args):
            return _bad_token()
        r = await _send("POST", f"/{slug}/bind-pipeline",
                        {"slot": slot, "pipeline_id": pipeline_id, "summary": summary, "description": summary})
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_set_confirm_check_nl(slug: str, text: str, confirm_token: str | None = None) -> dict:
        """[NL path — slower] Set the CONFIRM gate from plain text; the platform
        translates it into a check pipeline. Prefer rule_bind_checkpoint. Two-phase."""
        args = {"slug": slug, "text": text}
        if not confirm_token:
            return _need_confirm("rule_set_confirm_check_nl", args,
                f"SET confirm-check on {slug} from text (platform will translate): \"{text[:80]}\"")
        if confirm_token != _token("rule_set_confirm_check_nl", args):
            return _bad_token()
        r = await _send("POST", f"/{slug}/confirm-check", {"text": text})
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_add_step_nl(slug: str, text: str, confirm_token: str | None = None) -> dict:
        """[NL path — slower] Append a checklist step from plain text; the platform
        translates it into a check pipeline. Prefer building + rule_bind_checkpoint. Two-phase."""
        args = {"slug": slug, "text": text}
        if not confirm_token:
            return _need_confirm("rule_add_step_nl", args,
                f"ADD step to {slug} from text (platform will translate): \"{text[:80]}\"")
        if confirm_token != _token("rule_add_step_nl", args):
            return _bad_token()
        r = await _send("POST", f"/{slug}/steps", {"text": text})
        return {"slug": r.get("slug"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_disable(slug: str, confirm_token: str | None = None) -> dict:
        """Disable a rule (revert status to draft so the patrol engine stops running it).
        Safe + reversible, but still two-phase confirm for consistency."""
        args = {"slug": slug}
        if not confirm_token:
            return _need_confirm("rule_disable", args, f"DISABLE rule {slug} (status -> draft; stops auto-running).")
        if confirm_token != _token("rule_disable", args):
            return _bad_token()
        r = await _send("PUT", f"/{slug}", {"status": "draft"})
        return {"slug": r.get("slug"), "status": r.get("status"), "summary": _summ(r)}

    @mcp.tool()
    async def rule_delete(slug: str, confirm_token: str | None = None) -> dict:
        """Delete a rule. Two-phase; the preview surfaces what will be lost (trigger,
        steps, status) so the user can make an informed call."""
        args = {"slug": slug}
        if not confirm_token:
            try:
                r = await _get(f"/{slug}")
                impact = _summ(r)
            except Exception:
                impact = "(could not load rule detail)"
            return _need_confirm("rule_delete", args, f"DELETE rule {slug}. Impact: {impact}")
        if confirm_token != _token("rule_delete", args):
            return _bad_token()
        await _send("DELETE", f"/{slug}")
        return {"deleted": slug}
