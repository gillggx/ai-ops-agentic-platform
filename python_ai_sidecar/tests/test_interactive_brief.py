"""Unit tests for the interactive-brief backend (2026-06-15).

Covers the pure pieces of dimensional_clarifier that the brief relies on:
  - degenerate CONFIRM decision when nothing is ambiguous (always=True)
  - 其它 (OTHER_VALUE) free-text option appended per decision (include_other)
  - augment_goal_for_resolutions: canonical hint vs 其它 free-text vs CONFIRM
"""

from __future__ import annotations

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
