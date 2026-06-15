"""Unit tests for the interactive-brief backend (2026-06-15).

Covers the pure pieces of dimensional_clarifier that the brief relies on:
  - degenerate CONFIRM decision when nothing is ambiguous (always=True)
  - 其它 (OTHER_VALUE) free-text option appended per decision (include_other)
  - augment_goal_for_resolutions: canonical hint vs 其它 free-text vs CONFIRM
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier import (
    CONFIRM_DIMENSION,
    OTHER_VALUE,
    Dimension,
    Option,
    augment_goal_for_resolutions,
    build_clarifications,
)


@pytest.mark.asyncio
async def test_build_clarifications_degenerate_confirm_when_no_ambiguity():
    """A fully clear prompt fires no detectors → always=True returns one
    degenerate CONFIRM decision so the brief still has a 'start' point."""
    out = await build_clarifications(
        user_msg="EQP-01 STEP_001 過去 7 天的 xbar 趨勢圖",
        declared_inputs=None,
        pipeline_snapshot=None,
        include_other=True,
        always=True,
    )
    assert len(out) == 1
    assert out[0]["dimension"] == CONFIRM_DIMENSION
    assert out[0]["options"][0]["value"] == "go"


@pytest.mark.asyncio
async def test_build_clarifications_legacy_empty_when_no_ambiguity():
    """Legacy callers (always=False) still get [] = no card."""
    out = await build_clarifications(
        user_msg="EQP-01 STEP_001 過去 7 天的 xbar 趨勢圖",
        declared_inputs=None, pipeline_snapshot=None,
    )
    assert out == []


@pytest.mark.asyncio
async def test_build_clarifications_appends_other_option():
    """include_other=True appends a 其它 free-text option to each decision."""
    fake_dims = [Dimension(
        dimension="scope", question="範圍？",
        options=[Option(value="single_via_param", label="單台"),
                 Option(value="all_machines", label="全廠")],
        default="single_via_param",
    )]
    with patch(
        "python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier.detect_dimensions",
        return_value=fake_dims,
    ), patch(
        "python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier.enrich_dimensions",
        new=AsyncMock(return_value=fake_dims),
    ):
        out = await build_clarifications(
            user_msg="各機台 OOC", declared_inputs=None, pipeline_snapshot=None,
            include_other=True, always=True,
        )
    assert len(out) == 1
    opts = out[0]["options"]
    assert opts[-1]["value"] == OTHER_VALUE
    assert opts[-1].get("free_text") is True
    # original options preserved before 其它
    assert {o["value"] for o in opts[:-1]} == {"single_via_param", "all_machines"}


def test_augment_goal_canonical_hint():
    goal = augment_goal_for_resolutions("base", {"scope": "all_machines"})
    assert "base" in goal
    assert "不要" in goal and "filter" in goal  # the all_machines hint


def test_augment_goal_free_text_other():
    """其它 free-text (unmapped value) → spliced as the user's own words."""
    goal = augment_goal_for_resolutions("base", {"scope": "只要 EQP-01 跟 EQP-02 兩台"})
    assert "只要 EQP-01 跟 EQP-02 兩台" in goal
    assert "補充說明" in goal


def test_augment_goal_ignores_confirm_and_other_sentinel():
    """The degenerate CONFIRM pick and a bare OTHER_VALUE carry no semantics."""
    assert augment_goal_for_resolutions("base", {CONFIRM_DIMENSION: "go"}) == "base"
    assert augment_goal_for_resolutions("base", {"scope": OTHER_VALUE}) == "base"


# ── Plan brief (option a) ───────────────────────────────────────────────────


def _fake_llm(text: str):
    client = AsyncMock()
    client.create = AsyncMock(return_value=SimpleNamespace(text=text))
    return client


@pytest.mark.asyncio
async def test_build_plan_brief_shape_and_other_appended():
    from python_ai_sidecar.agent_orchestrator_v2 import brief_planner as bp
    payload = {
        "is_pipeline_request": True,
        "summary": "EQP-01~05 xbar 趨勢",
        "plan_steps": [
            {"id": "s1", "title": "抓 process history",
             "decision": {"question": "幾天?", "options": [
                 {"value": "7d", "label": "7 天", "as_goal": "time_range=7d"},
                 {"value": "14d", "label": "14 天", "as_goal": "time_range=14d"}]}},
            {"id": "s2", "title": "整理時序", "decision": None},
        ],
    }
    with patch.object(bp, "get_llm_client", return_value=_fake_llm(json.dumps(payload))):
        out = await bp.build_plan_brief("EQP-01~05 STEP_001 xbar 趨勢")
    assert out["is_pipeline_request"] is True
    steps = out["plan_steps"]
    assert [s["id"] for s in steps] == ["s1", "s2"]
    assert steps[1]["decision"] is None
    opts = steps[0]["decision"]["options"]
    assert opts[-1]["value"] == bp.OTHER_VALUE and opts[-1].get("free_text") is True
    assert steps[0]["decision"]["dimension"] == "s1"   # keyed on step id


@pytest.mark.asyncio
async def test_build_plan_brief_knowledge_question_passthrough():
    from python_ai_sidecar.agent_orchestrator_v2 import brief_planner as bp
    with patch.object(bp, "get_llm_client",
                      return_value=_fake_llm('{"is_pipeline_request": false}')):
        out = await bp.build_plan_brief("Cpk 是什麼")
    assert out == {"is_pipeline_request": False}


@pytest.mark.asyncio
async def test_build_plan_brief_fallback_on_bad_json():
    from python_ai_sidecar.agent_orchestrator_v2 import brief_planner as bp
    with patch.object(bp, "get_llm_client", return_value=_fake_llm("not json")):
        out = await bp.build_plan_brief("anything")
    assert out["is_pipeline_request"] is True
    assert len(out["plan_steps"]) == 1   # degenerate fallback


def test_clarifications_and_goal_mapping():
    from python_ai_sidecar.agent_orchestrator_v2 import brief_planner as bp
    plan = [
        {"id": "s1", "title": "f", "decision": {"dimension": "s1", "question": "幾天?",
         "options": [{"value": "7d", "label": "7 天", "as_goal": "time_range=7d"},
                     {"value": bp.OTHER_VALUE, "label": "其它", "as_goal": "", "free_text": True}]}},
        {"id": "s2", "title": "g", "decision": None},
    ]
    clars = bp.clarifications_from_plan(plan)
    assert len(clars) == 1 and clars[0]["dimension"] == "s1"
    # id → as_goal mapping (safety net); free-text passes through
    assert bp.goal_resolutions_from_selections(plan, {"s1": "7d"}) == {"s1": "time_range=7d"}
    assert bp.goal_resolutions_from_selections(plan, {"s1": "只要 14 天"}) == {"s1": "只要 14 天"}
