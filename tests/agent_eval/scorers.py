"""Scorer functions for the eval harness.

Each scorer:
  - takes (case_expect_dict, ObservedRun) → ScoreResult | None
  - returns None when the expectation key isn't in the case (skip silently)
  - returns ScoreResult(passed, message, name) otherwise

Add new scorers by appending to ALL_SCORERS at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from tests.agent_eval.runner import ObservedRun


@dataclass
class ScoreResult:
    name: str
    passed: bool
    message: str = ""


# ── Per-expectation scorers ───────────────────────────────────────────


def http_ok(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """Always-on basic check — HTTP must be 2xx."""
    if obs.http_status >= 400 or obs.http_status == 0:
        return ScoreResult(
            name="http_ok",
            passed=False,
            message=f"http={obs.http_status} error={obs.error}",
        )
    return ScoreResult(name="http_ok", passed=True, message=f"http={obs.http_status}")


def sse_event_types_include(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`sse_event_types_include: [advisor_answer, done]` — all listed types must
    appear at least once in the SSE stream."""
    required = expect.get("sse_event_types_include")
    if required is None:
        return None
    missing = [t for t in required if t not in obs.event_type_set]
    if missing:
        return ScoreResult(
            name="sse_event_types_include",
            passed=False,
            message=f"missing event types: {missing} (got {sorted(obs.event_type_set)})",
        )
    return ScoreResult(
        name="sse_event_types_include",
        passed=True,
        message=f"all required events present: {required}",
    )


def sse_event_types_exclude(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`sse_event_types_exclude: [advisor_answer]` — none of the listed types
    may appear (e.g. KNOWLEDGE shouldn't trigger advisor_answer)."""
    forbidden = expect.get("sse_event_types_exclude")
    if forbidden is None:
        return None
    found = [t for t in forbidden if t in obs.event_type_set]
    if found:
        return ScoreResult(
            name="sse_event_types_exclude",
            passed=False,
            message=f"forbidden event types appeared: {found}",
        )
    return ScoreResult(
        name="sse_event_types_exclude",
        passed=True,
        message=f"none of {forbidden} appeared",
    )


def advisor_kind(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`advisor_kind: explain|compare|recommend|ambiguous` — first
    advisor_answer event's `kind` field must match."""
    expected = expect.get("advisor_kind")
    if expected is None:
        return None
    data = obs.first_event_data("advisor_answer")
    if data is None:
        return ScoreResult(
            name="advisor_kind",
            passed=False,
            message=f"no advisor_answer event (expected kind={expected})",
        )
    actual = data.get("kind")
    return ScoreResult(
        name="advisor_kind",
        passed=actual == expected,
        message=f"kind expected={expected} actual={actual}",
    )


def answer_contains_any(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`answer_contains_any: [keyword1, keyword2]` — advisor markdown answer
    (or chat synthesis text) must contain at least one of the keywords."""
    keywords = expect.get("answer_contains_any")
    if keywords is None:
        return None
    # Try advisor_answer first, then any text-bearing event.
    text = ""
    adv = obs.first_event_data("advisor_answer")
    if adv:
        text = str(adv.get("markdown", ""))
    if not text:
        # Concatenate all data values as a fallback (chat path / synthesis).
        text = " ".join(
            str(v) for e in obs.sse_events
            for v in e.get("data", {}).values()
            if isinstance(v, str)
        )
    text_lower = text.lower()
    matched = [k for k in keywords if k.lower() in text_lower]
    return ScoreResult(
        name="answer_contains_any",
        passed=len(matched) > 0,
        message=f"matched={matched} (looked for {keywords})",
    )


def candidates_include_any(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`candidates_include_any: [block_xbar_r, block_imr]` — advisor RECOMMEND
    candidates list must contain at least one expected block name."""
    wanted = expect.get("candidates_include_any")
    if wanted is None:
        return None
    adv = obs.first_event_data("advisor_answer")
    if adv is None:
        return ScoreResult(
            name="candidates_include_any",
            passed=False,
            message=f"no advisor_answer (expected one of {wanted})",
        )
    candidates = adv.get("candidates") or []
    matched = [c for c in candidates if c in wanted]
    return ScoreResult(
        name="candidates_include_any",
        passed=len(matched) > 0,
        message=f"got {candidates} matched={matched}",
    )


def block_name_equals(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`block_name_equals: block_xbar_r` — for advisor EXPLAIN, the
    `block_name` payload must match (verifies extract_block_target)."""
    expected = expect.get("block_name_equals")
    if expected is None:
        return None
    adv = obs.first_event_data("advisor_answer")
    if adv is None:
        return ScoreResult(name="block_name_equals", passed=False, message="no advisor_answer")
    actual = adv.get("block_name")
    return ScoreResult(
        name="block_name_equals",
        passed=actual == expected,
        message=f"block_name expected={expected} actual={actual}",
    )


def min_event_count(expect: dict[str, Any], obs: "ObservedRun") -> ScoreResult | None:
    """`min_event_count: 3` — must have at least N SSE events (sanity check
    that the orchestrator at least responded with content)."""
    n = expect.get("min_event_count")
    if n is None:
        return None
    actual = len(obs.sse_events)
    return ScoreResult(
        name="min_event_count",
        passed=actual >= n,
        message=f"events={actual} (min={n})",
    )


# ── Registry ──────────────────────────────────────────────────────────

ALL_SCORERS: list[Callable[[dict[str, Any], "ObservedRun"], ScoreResult | None]] = [
    http_ok,
    sse_event_types_include,
    sse_event_types_exclude,
    advisor_kind,
    answer_contains_any,
    candidates_include_any,
    block_name_equals,
    min_event_count,
]
