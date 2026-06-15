"""Plan-structured collaborative brief (2026-06-15, option (a)).

One LLM call turns a build request into a step-by-step PLAN where each step
that has a REAL material choice carries a question + options (Claude-cowork
style). The user resolves the choices; their picks (each option's `as_goal`
guidance, or 其它 free-text) splice into the build goal via
`dimensional_clarifier.augment_goal_for_resolutions`.

Design boundary (see Todos 0b): the brief plan is for ALIGNMENT + collecting
choices, NOT the executed plan — the builder's own goal_plan still runs. So a
slightly-off brief plan just means slightly-off guidance, recoverable. Flow
(always show brief, build once all decisions resolved) stays in the graph;
the LLM only does the reasoning (propose steps + relevant questions).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Matches dimensional_clarifier.OTHER_VALUE — keep in sync.
OTHER_VALUE = "__other__"

_SYSTEM = """You turn a manufacturing-engineer's build request into a SHORT,
collaborative BRIEF: a step-by-step plan where steps with a real choice ask the
user ONE focused question with options. The user picks before building.

## STEP 0 — is this a pipeline-building request?
If it's a knowledge / definition / how-does-X-work question (not building a
data pipeline), output `{"is_pipeline_request": false}` and nothing else.

## If it IS a build request, write the plan
Output 2-4 ordered steps describing what you'll do (fetch → transform → chart,
etc.). For EACH step, decide: does it have a choice that MATERIALLY changes the
result and that the user should make? If yes, attach ONE decision. If the step
is obvious (no real choice), set `decision: null`.

Attach a decision ONLY for genuinely open, result-changing choices, e.g.:
  - time range to fetch (7d / 14d / 30d / ...)
  - chart presentation (one combined chart with series=toolID vs one per machine)
  - grouping dimension (by tool / by step / by recipe)
  - threshold / OOC criterion
  - scope (single machine vs across machines)
Do NOT ask about things already specified in the request, and do NOT invent
trivial questions. AT MOST 3 decisions total across all steps.

Each option needs:
  - value: a short stable id (ascii, no spaces), e.g. "7d", "combined"
  - label: short user-facing text in the user's language
  - as_goal: ONE line of concrete guidance for the pipeline builder describing
    what this choice means (the builder reads this; be specific — column names,
    series/facet, filters), e.g. "single line_chart, series_field=toolID,
    color per machine".

Match the user's language (Traditional Chinese if they typed 中文).

Output JSON only, no fences:
{
  "is_pipeline_request": true,
  "summary": "<one-line business-语意 summary of what gets built>",
  "plan_steps": [
    {"id": "s1", "title": "<step title>",
     "decision": {"question": "<focused question>",
                  "options": [
                    {"value": "7d", "label": "7 天", "as_goal": "time_range=7d"},
                    {"value": "14d", "label": "14 天", "as_goal": "time_range=14d"}
                  ]}},
    {"id": "s2", "title": "<obvious step>", "decision": null}
  ]
}
"""


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    return text


def _norm_options(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        val = str(o.get("value") or "").strip()
        if not val or val == OTHER_VALUE:
            continue
        out.append({
            "value": val,
            "label": str(o.get("label") or val).strip(),
            "as_goal": str(o.get("as_goal") or o.get("label") or val).strip(),
        })
    return out


async def build_plan_brief(user_msg: str) -> dict[str, Any]:
    """Return {is_pipeline_request, summary, plan_steps} for the brief.

    Never raises — on any failure returns a minimal fallback brief (one step,
    one degenerate confirm) so the always-align gate still works.
    """
    try:
        client = get_llm_client()
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg or ""}],
            max_tokens=900,
        )
        data = json.loads(_strip_fence(resp.text or ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("build_plan_brief: LLM/parse failed (%s) — fallback brief", e)
        return _fallback_brief()

    if data.get("is_pipeline_request") is False:
        return {"is_pipeline_request": False}

    steps_in = data.get("plan_steps") or []
    plan_steps: list[dict[str, Any]] = []
    n_decisions = 0
    for i, s in enumerate(steps_in):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or f"s{i + 1}")
        title = str(s.get("title") or "").strip()
        if not title:
            continue
        decision = None
        d = s.get("decision")
        if isinstance(d, dict) and n_decisions < 3:
            opts = _norm_options(d.get("options"))
            if len(opts) >= 2:
                # append the 其它 free-text escape (deterministic)
                opts.append({"value": OTHER_VALUE, "label": "其它（自己描述）",
                             "as_goal": "", "free_text": True})
                decision = {
                    "dimension": sid,  # resolution keys on the step id
                    "question": str(d.get("question") or "").strip() or "怎麼做？",
                    "options": opts,
                }
                n_decisions += 1
        plan_steps.append({"id": sid, "title": title, "decision": decision})

    if not plan_steps:
        return _fallback_brief()
    return {
        "is_pipeline_request": True,
        "summary": str(data.get("summary") or "").strip(),
        "plan_steps": plan_steps,
    }


def _fallback_brief() -> dict[str, Any]:
    """Minimal always-align brief when the planner can't produce one."""
    return {
        "is_pipeline_request": True,
        "summary": "",
        "plan_steps": [{
            "id": "s1", "title": "建立你要的 pipeline",
            "decision": {
                "dimension": "__confirm__",
                "question": "這樣建立可以嗎？",
                "options": [{"value": "go", "label": "開始建立", "as_goal": ""}],
            },
        }],
    }


def clarifications_from_plan(plan_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the per-step decisions into the clarifications list the card's
    resolution logic consumes (each carries its step's `dimension`)."""
    return [s["decision"] for s in (plan_steps or [])
            if isinstance(s, dict) and isinstance(s.get("decision"), dict)]


def goal_resolutions_from_selections(
    plan_steps: list[dict[str, Any]], selections: dict[str, str],
) -> dict[str, str]:
    """Map the card's {dimension: chosen_option_value | free_text} into
    {dimension: as_goal | free_text} for augment_goal_for_resolutions.

    The frontend already maps a picked option to its `as_goal` before sending,
    so values usually ARE guidance text; this is a backend safety net that
    resolves any raw option value left as an id back to its as_goal."""
    by_dim: dict[str, dict[str, str]] = {}
    for s in plan_steps or []:
        d = s.get("decision") if isinstance(s, dict) else None
        if isinstance(d, dict):
            by_dim[d.get("dimension")] = {
                o.get("value"): o.get("as_goal") or o.get("label") or ""
                for o in (d.get("options") or []) if isinstance(o, dict)
            }
    out: dict[str, str] = {}
    for dim, val in (selections or {}).items():
        opts = by_dim.get(dim) or {}
        out[dim] = opts.get(val, val)  # id → as_goal, else keep (free-text)
    return out
