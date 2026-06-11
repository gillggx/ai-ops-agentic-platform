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
