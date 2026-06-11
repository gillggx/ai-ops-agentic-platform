"""Tests for ENABLE_AUTO_SIGNAL behavior in agentic_phase_loop sub-phase machinery."""

from __future__ import annotations

import importlib

import pytest


def _reload_with_env(monkeypatch, *, prompt_cache: str, auto_signal: str):
    monkeypatch.setenv("ENABLE_PROMPT_CACHE", prompt_cache)
    monkeypatch.setenv("ENABLE_AUTO_SIGNAL", auto_signal)
    import python_ai_sidecar.config as cfg

    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff

    importlib.reload(ff)
    return cfg, ff


def test_pick_filter_excludes_add_node_when_auto_signal_off(monkeypatch):
    _reload_with_env(monkeypatch, prompt_cache="1", auto_signal="0")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _filter_tool_specs_for_subphase,
    )

    specs = [{"name": n} for n in [
        "commit_pick", "add_node", "connect", "inspect_node_output",
    ]]
    out = {s["name"] for s in _filter_tool_specs_for_subphase(specs, "pick")}
    assert "add_node" not in out
    assert "commit_pick" in out


def test_pick_filter_includes_add_node_when_auto_signal_on(monkeypatch):
    _reload_with_env(monkeypatch, prompt_cache="1", auto_signal="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _filter_tool_specs_for_subphase,
    )

    specs = [{"name": n} for n in [
        "commit_pick", "add_node", "connect", "inspect_node_output",
    ]]
    out = {s["name"] for s in _filter_tool_specs_for_subphase(specs, "pick")}
    assert "add_node" in out
    assert "commit_pick" in out  # legacy path still allowed


def test_transition_pick_add_node_to_construct(monkeypatch):
    # _TRANSITIONS is a module-level constant and doesn't depend on env at
    # transition-eval time; the env-on path is just additive.
    _reload_with_env(monkeypatch, prompt_cache="1", auto_signal="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _next_subphase,
    )

    assert _next_subphase("pick", "add_node") == "construct"
    assert _next_subphase("pick", "commit_pick") == "construct"
    # Tune → add_node now also routes to construct (chain shortcut)
    assert _next_subphase("tune", "add_node") == "construct"


def test_subphase_hint_mentions_shortcut_only_when_auto_signal_on(monkeypatch):
    _reload_with_env(monkeypatch, prompt_cache="1", auto_signal="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_subphase_hint,
    )

    hint_on = _build_subphase_hint("pick", {})
    assert "add_node(block_name" in hint_on
    assert "auto-commits" in hint_on

    _reload_with_env(monkeypatch, prompt_cache="1", auto_signal="0")
    # re-import the loop module so it re-resolves the flag
    import python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop as loop_mod

    importlib.reload(loop_mod)
    hint_off = loop_mod._build_subphase_hint("pick", {})
    assert "cannot add_node from this" in hint_off
