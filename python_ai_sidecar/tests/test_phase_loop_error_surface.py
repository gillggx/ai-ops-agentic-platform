"""2026-06-25 hardening #3 — surface block-execution errors on run_verifier.

Root cause (SLASH-17 trace): when the agent emits run_verifier (a signal tool,
no mutation), the loop pointed the verifier at the canvas terminal but did NOT
re-preview it, so phase_verifier read a stale/absent exec_trace entry. A failing
terminal then surfaced error=null -> "(no error message captured)" and the agent
looped blind (block_sort flailed 44 rounds). Fix: re-preview the terminal NOW and
coalesce the real error into the snapshot.
"""
from __future__ import annotations

import asyncio
import types

from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
    _coalesce_preview_error,
    _fresh_terminal_snapshot,
)


# ── _coalesce_preview_error (pure) ──────────────────────────────────

def test_coalesce_prefers_singular_error():
    assert _coalesce_preview_error({"error": "boom", "errors": []}) == "boom"


def test_coalesce_validator_errors_list_of_dicts():
    pv = {"error": None, "errors": [
        {"code": "C6_PARAM_SCHEMA", "message": "column 'x' missing"},
        {"rule": "C4_PORT_COMPAT", "hint": "wrong port"},
    ]}
    out = _coalesce_preview_error(pv)
    assert "[C6_PARAM_SCHEMA] column 'x' missing" in out
    assert "[C4_PORT_COMPAT] wrong port" in out


def test_coalesce_errors_list_of_strings():
    assert _coalesce_preview_error({"errors": ["bad", "worse"]}) == "bad | worse"


def test_coalesce_nothing_returns_none():
    assert _coalesce_preview_error({"status": "failed"}) is None
    assert _coalesce_preview_error({"error": None, "errors": []}) is None


# ── _fresh_terminal_snapshot (re-preview captures status+error) ──────

class _FakeToolset:
    def __init__(self, pv):
        self._pv = pv

    async def preview(self, node_id, sample_size=5):
        return self._pv


def _pipeline(node_id, block_id):
    node = types.SimpleNamespace(id=node_id, block_id=block_id)
    return types.SimpleNamespace(nodes=[node])


def test_fresh_snapshot_captures_failure_error():
    ts = _FakeToolset({"status": "failed", "rows": None, "error": "sort col missing"})
    snap = asyncio.run(_fresh_terminal_snapshot(
        ts, _pipeline("n5", "block_sort"), "n5", round_n=7))
    assert snap["status"] == "failed"
    assert snap["error"] == "sort col missing"      # no longer null -> agent can fix
    assert snap["block_id"] == "block_sort"
    assert snap["real_id"] == "n5"


def test_fresh_snapshot_captures_validator_errors():
    ts = _FakeToolset({"status": "validation_error",
                       "errors": [{"code": "C6", "message": "need column"}]})
    snap = asyncio.run(_fresh_terminal_snapshot(
        ts, _pipeline("n2", "block_bar_chart"), "n2", round_n=3))
    assert snap["status"] == "validation_error"
    assert "[C6] need column" in snap["error"]


def test_fresh_snapshot_success_has_no_error():
    ts = _FakeToolset({"status": "success", "rows": 12, "error": None})
    snap = asyncio.run(_fresh_terminal_snapshot(
        ts, _pipeline("n1", "block_filter"), "n1", round_n=1))
    assert snap["status"] == "success"
    assert snap["error"] is None
    assert snap["rows"] == 12
