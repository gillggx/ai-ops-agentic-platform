"""Unit tests for python_ai_sidecar.feature_flags."""

from __future__ import annotations

import importlib

import pytest


def test_parse_header_empty_returns_empty_dict():
    from python_ai_sidecar.feature_flags import parse_feature_flags_header

    assert parse_feature_flags_header("") == {}
    assert parse_feature_flags_header("   ") == {}


def test_parse_header_on_off():
    from python_ai_sidecar.feature_flags import parse_feature_flags_header

    got = parse_feature_flags_header("prompt_cache:on,auto_signal:off")
    assert got == {"prompt_cache": True, "auto_signal": False}


def test_parse_header_accepts_synonyms():
    from python_ai_sidecar.feature_flags import parse_feature_flags_header

    assert parse_feature_flags_header("prompt_cache:1")["prompt_cache"] is True
    assert parse_feature_flags_header("prompt_cache:true")["prompt_cache"] is True
    assert parse_feature_flags_header("prompt_cache:yes")["prompt_cache"] is True
    assert parse_feature_flags_header("prompt_cache:0")["prompt_cache"] is False
    assert parse_feature_flags_header("prompt_cache:false")["prompt_cache"] is False
    assert parse_feature_flags_header("prompt_cache:no")["prompt_cache"] is False


def test_parse_header_ignores_unknown_flags_and_malformed_parts():
    from python_ai_sidecar.feature_flags import parse_feature_flags_header

    got = parse_feature_flags_header("unknown:on,prompt_cache:on,broken,auto_signal:")
    assert got == {"prompt_cache": True}


def test_parse_header_accepts_round1_flags():
    """Round 1 (2026-06-12): atomic_add_connect, auto_verifier, strict_tool_id."""
    from python_ai_sidecar.feature_flags import parse_feature_flags_header

    got = parse_feature_flags_header(
        "atomic_add_connect:on,auto_verifier:on,strict_tool_id:off"
    )
    assert got == {
        "atomic_add_connect": True,
        "auto_verifier": True,
        "strict_tool_id": False,
    }


def test_round1_flag_helpers_respect_overrides(monkeypatch):
    monkeypatch.setenv("ENABLE_ATOMIC_ADD_CONNECT", "0")
    monkeypatch.setenv("ENABLE_AUTO_VERIFIER", "0")
    monkeypatch.setenv("ENABLE_STRICT_TOOL_ID", "0")
    import python_ai_sidecar.config as cfg

    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff

    importlib.reload(ff)

    assert ff.is_atomic_add_connect_enabled() is False
    assert ff.is_auto_verifier_enabled() is False
    assert ff.is_strict_tool_id_enabled() is False

    tok = ff.set_request_overrides({
        "atomic_add_connect": True,
        "auto_verifier": True,
        "strict_tool_id": True,
    })
    try:
        assert ff.is_atomic_add_connect_enabled() is True
        assert ff.is_auto_verifier_enabled() is True
        assert ff.is_strict_tool_id_enabled() is True
    finally:
        ff.reset_request_overrides(tok)


def test_round1_env_defaults(monkeypatch):
    monkeypatch.setenv("ENABLE_ATOMIC_ADD_CONNECT", "1")
    monkeypatch.setenv("ENABLE_AUTO_VERIFIER", "yes")
    monkeypatch.setenv("ENABLE_STRICT_TOOL_ID", "true")
    import python_ai_sidecar.config as cfg

    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff

    importlib.reload(ff)

    assert ff.is_atomic_add_connect_enabled() is True
    assert ff.is_auto_verifier_enabled() is True
    assert ff.is_strict_tool_id_enabled() is True


def test_no_duplicate_node_flag_round_trip(monkeypatch):
    """Round 2 (2026-06-12): orphan-duplicate guard flag."""
    from python_ai_sidecar.feature_flags import parse_feature_flags_header
    assert parse_feature_flags_header("no_duplicate_node:on") == {"no_duplicate_node": True}

    monkeypatch.setenv("ENABLE_NO_DUPLICATE_NODE", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    assert ff.is_no_duplicate_node_enabled() is False

    tok = ff.set_request_overrides({"no_duplicate_node": True})
    try:
        assert ff.is_no_duplicate_node_enabled() is True
    finally:
        ff.reset_request_overrides(tok)
    assert ff.is_no_duplicate_node_enabled() is False


def test_rich_canvas_snapshot_flag_round_trip(monkeypatch):
    """Round 3 (2026-06-12): context-aware per-sub-phase prompt flag."""
    from python_ai_sidecar.feature_flags import parse_feature_flags_header
    assert parse_feature_flags_header("rich_canvas_snapshot:on") == {"rich_canvas_snapshot": True}

    monkeypatch.setenv("ENABLE_RICH_CANVAS_SNAPSHOT", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    assert ff.is_rich_canvas_snapshot_enabled() is False

    tok = ff.set_request_overrides({"rich_canvas_snapshot": True})
    try:
        assert ff.is_rich_canvas_snapshot_enabled() is True
    finally:
        ff.reset_request_overrides(tok)
    assert ff.is_rich_canvas_snapshot_enabled() is False


def test_plan_knowledge_flag_round_trip(monkeypatch):
    """Round 4 (2026-06-12): goal_plan agent_knowledge injection flag."""
    from python_ai_sidecar.feature_flags import parse_feature_flags_header
    assert parse_feature_flags_header("plan_knowledge:on") == {"plan_knowledge": True}

    monkeypatch.setenv("ENABLE_PLAN_KNOWLEDGE", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    assert ff.is_plan_knowledge_enabled() is False

    tok = ff.set_request_overrides({"plan_knowledge": True})
    try:
        assert ff.is_plan_knowledge_enabled() is True
    finally:
        ff.reset_request_overrides(tok)
    assert ff.is_plan_knowledge_enabled() is False


def test_v58_knowledge_layer_flags_round_trip(monkeypatch):
    """V58 (2026-06-14): execute_knowledge + layered_plan_knowledge flags."""
    from python_ai_sidecar.feature_flags import parse_feature_flags_header
    assert parse_feature_flags_header(
        "execute_knowledge:on,layered_plan_knowledge:on"
    ) == {"execute_knowledge": True, "layered_plan_knowledge": True}

    monkeypatch.setenv("ENABLE_EXECUTE_KNOWLEDGE", "0")
    monkeypatch.setenv("ENABLE_LAYERED_PLAN_KNOWLEDGE", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    assert ff.is_execute_knowledge_enabled() is False
    assert ff.is_layered_plan_knowledge_enabled() is False

    tok = ff.set_request_overrides({
        "execute_knowledge": True, "layered_plan_knowledge": True,
    })
    try:
        assert ff.is_execute_knowledge_enabled() is True
        assert ff.is_layered_plan_knowledge_enabled() is True
    finally:
        ff.reset_request_overrides(tok)
    assert ff.is_execute_knowledge_enabled() is False
    assert ff.is_layered_plan_knowledge_enabled() is False


def test_overrides_take_precedence_over_env(monkeypatch):
    # Force default-off envs, then verify override flips both.
    monkeypatch.setenv("ENABLE_PROMPT_CACHE", "0")
    monkeypatch.setenv("ENABLE_AUTO_SIGNAL", "0")
    import python_ai_sidecar.config as cfg

    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff

    importlib.reload(ff)

    assert ff.is_prompt_cache_enabled() is False
    assert ff.is_auto_signal_enabled() is False

    tok = ff.set_request_overrides({"prompt_cache": True, "auto_signal": True})
    try:
        assert ff.is_prompt_cache_enabled() is True
        assert ff.is_auto_signal_enabled() is True
    finally:
        ff.reset_request_overrides(tok)

    assert ff.is_prompt_cache_enabled() is False
    assert ff.is_auto_signal_enabled() is False


def test_env_defaults_apply_when_no_override(monkeypatch):
    monkeypatch.setenv("ENABLE_PROMPT_CACHE", "1")
    monkeypatch.setenv("ENABLE_AUTO_SIGNAL", "0")
    import python_ai_sidecar.config as cfg

    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff

    importlib.reload(ff)

    assert ff.is_prompt_cache_enabled() is True
    assert ff.is_auto_signal_enabled() is False
