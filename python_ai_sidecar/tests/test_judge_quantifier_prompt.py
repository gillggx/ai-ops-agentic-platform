"""v30.17i — judge prompt must encode the 20% ratio rule for N-count
value_desc, so resource-limited data sources don't trigger spurious
build failures.

This is a static prompt-content test (the judge is LLM-based; a true
behavioural test would require live LLM and is too expensive/flaky for
CI). It guards against future prompt edits silently dropping the rule.

Real-world motivation (2026-05-17):
  user: "查 EQP-01 STEP_001 最近 100 筆 xbar 趨勢"
  block_process_history returned only 7 rows (simulator limit)
  → judge rejected p1 ('100筆' not met) → entire build stuck
  Fix: rows >= 20% of N → match with note. rows < 20% → reject.
"""
from __future__ import annotations

import inspect

from python_ai_sidecar.agent_builder.graph_build.nodes import phase_verifier


def _read_judge_source() -> str:
    """Get the source of _llm_judge_phase_outcome (where the prompt lives)."""
    return inspect.getsource(phase_verifier._llm_judge_phase_outcome)


def test_judge_prompt_has_n_count_ratio_rule():
    src = _read_judge_source()
    # Match rule must be visible
    assert "rows >= N" in src
    assert "0.2" in src or "20%" in src, (
        "Judge prompt missing the 20% threshold rule for resource-limited "
        "data sources — re-add or quantifier requests will fail spuriously"
    )


def test_judge_prompt_has_match_with_note_branch():
    src = _read_judge_source()
    # Reason should mention the partial-match note path
    assert "資料源僅" in src or "少於要求" in src, (
        "Judge prompt should instruct LLM to note partial data rather "
        "than silently reject"
    )


def test_judge_prompt_keeps_strict_singular_rule():
    """Don't loosen the single-row 'last/latest' case — that's strict by design."""
    src = _read_judge_source()
    assert "最後一次" in src or "latest" in src
    assert "rows == 1" in src, (
        "Single-row 'last/latest' rule must stay strict; 放寬 ratio rule "
        "only applies to N-count requests"
    )


def test_judge_prompt_has_all_quantifier_rule():
    src = _read_judge_source()
    assert "所有" in src or "all" in src
    assert "rows >= 2" in src
