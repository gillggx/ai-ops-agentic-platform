"""mcp_derivative.generator — offline tests for the pre-LLM lint, prompt
build, and JSON parse paths. Live LLM calls are NOT exercised here (those
need a separate live-API smoke test per CLAUDE.md feedback_self_smoke_before_user).
"""

from __future__ import annotations

import pytest

from python_ai_sidecar.mcp_derivative.generator import (
    MIN_DESCRIPTION_CHARS,
    PROMPT_VERSION,
    GenerateResult,
    _build_system_prompt,
    _build_user_prompt,
    _safe_parse_json,
    lint_mcp_description,
)


# ── lint_mcp_description ─────────────────────────────────────────────────────

def test_lint_empty_description_blocks_with_error():
    issues = lint_mcp_description("")
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert issues[0]["field"] == "description"


def test_lint_too_short_description_blocks_with_error():
    issues = lint_mcp_description("Too short.")
    assert any(i["severity"] == "error" for i in issues)


def test_lint_acceptable_description_passes_with_warns_only():
    # > MIN chars + has returns + has use-when keyword
    desc = (
        "This MCP returns the list of process events for a given lot. "
        "Use when investigating which steps a lot has been through. "
        "Returns: total count and list of {eventTime, toolID, lotID, step, "
        "spc_status} records. The spc_status field is 'PASS' or 'OOC'. "
        "Use case: trace a single lot's process flow end-to-end."
    )
    assert len(desc) >= MIN_DESCRIPTION_CHARS
    issues = lint_mcp_description(desc)
    assert all(i["severity"] != "error" for i in issues)


def test_lint_description_missing_returns_section_warns():
    desc = (
        "This MCP fetches process events for a lot. " * 10  # padding to clear MIN
    )
    issues = lint_mcp_description(desc)
    fields = [i["field"] for i in issues]
    # No "returns" / "回傳" → at least one warn flagging it
    severities = {i["severity"] for i in issues}
    assert "warn" in severities


def test_lint_description_with_chinese_keywords_recognised():
    desc = (
        "這個 MCP 用於查詢 lot 在 photo 站的 rework 紀錄。" * 3
        + "回傳: rework_records 陣列，每筆包含 reworkTime / lotID / step。"
        + "使用情境: 排查 lot 是否有重工歷史。" * 2
    )
    issues = lint_mcp_description(desc)
    # 中文 keywords 也應該觸發 has_returns_section / has_use_when —
    # 檢查不該出現「missing returns」或「missing use-when」這兩個結構性 warn
    msgs = [i["message"] for i in issues]
    assert not any("doesn't appear to document what the MCP returns" in m for m in msgs), \
        f"Chinese 回傳 should satisfy has_returns_section, got: {msgs}"
    assert not any("doesn't say WHEN to use" in m for m in msgs), \
        f"Chinese 使用情境 should satisfy has_use_when, got: {msgs}"


# ── _safe_parse_json ─────────────────────────────────────────────────────────

def test_parse_clean_json():
    text = '{"block_draft": {"name": "x"}, "skill_draft": null}'
    parsed = _safe_parse_json(text)
    assert parsed is not None
    assert parsed["block_draft"] == {"name": "x"}
    assert parsed["skill_draft"] is None


def test_parse_strips_code_fence():
    text = '```json\n{"a": 1}\n```'
    parsed = _safe_parse_json(text)
    assert parsed == {"a": 1}


def test_parse_strips_unmarked_fence():
    text = '```\n{"a": 1}\n```'
    parsed = _safe_parse_json(text)
    assert parsed == {"a": 1}


def test_parse_recovers_from_prepended_prose():
    text = 'Sure, here is the JSON: {"block_draft": {"x": 1}}'
    parsed = _safe_parse_json(text)
    assert parsed == {"block_draft": {"x": 1}}


def test_parse_returns_none_on_garbage():
    assert _safe_parse_json("not even close") is None
    assert _safe_parse_json("") is None
    assert _safe_parse_json("   ") is None


def test_parse_rejects_non_object_top_level():
    # List at top level is not a dict — must reject
    assert _safe_parse_json('[1, 2, 3]') is None


# ── prompt builders ──────────────────────────────────────────────────────────

def test_system_prompt_contains_principles_not_case_rules():
    sp = _build_system_prompt(want_block=True, want_skill=True)
    # Sanity: must contain the principle markers
    assert "PRINCIPLES" in sp
    assert "block_draft.description" in sp
    assert "skill_draft.use_case" in sp
    # CLAUDE.md rule 0: must NOT carry case-specific rules (e.g. ban listing
    # specific MCP names or columns). This is a guardrail to catch future
    # drift toward case lists. The check passes when the prompt has no
    # uppercase MCP-specific tokens like "REWORK_REQUEST" / "GET_PROCESS_INFO".
    forbidden_case_tokens = [
        "REWORK_REQUEST", "GET_PROCESS", "rework_records", "spc_status",
    ]
    for token in forbidden_case_tokens:
        assert token not in sp, (
            f"Case-specific token '{token}' leaked into system prompt — "
            "violates CLAUDE.md Core Principle 0"
        )


def test_system_prompt_honours_want_block_false():
    sp = _build_system_prompt(want_block=False, want_skill=True)
    assert "block_draft: set to null" in sp


def test_system_prompt_honours_want_skill_false():
    sp = _build_system_prompt(want_block=True, want_skill=False)
    assert "skill_draft: set to null" in sp


def test_user_prompt_includes_all_provided_context():
    up = _build_user_prompt(
        name="test_mcp",
        description="A test MCP description, sufficiently long.",
        input_schema={"fields": [{"name": "lot_id", "type": "string"}]},
        output_schema={"shape": "list"},
        api_config={"endpoint_url": "http://x:1234/test", "method": "POST"},
        want_block=True,
        want_skill=True,
    )
    assert "MCP_NAME: test_mcp" in up
    assert "A test MCP description" in up
    assert "lot_id" in up
    assert "endpoint_url" in up


def test_user_prompt_omits_unprovided_optionals():
    up = _build_user_prompt(
        name="x",
        description="d" * 300,
        input_schema=None,
        output_schema=None,
        api_config=None,
        want_block=True,
        want_skill=False,
    )
    assert "MCP_INPUT_SCHEMA" not in up
    assert "MCP_OUTPUT_SCHEMA" not in up
    assert "MCP_API_CONFIG" not in up
    assert "skill_draft: no (return null)" in up


# ── generate_derivatives short-circuit on lint errors ────────────────────────

@pytest.mark.asyncio
async def test_generate_derivatives_short_circuits_on_lint_error():
    from python_ai_sidecar.mcp_derivative.generator import generate_derivatives

    # Empty description → lint returns error → no LLM call should happen.
    # We intentionally do NOT mock the client; if generator tries to call,
    # it would raise (no ANTHROPIC_API_KEY in test env), and we want it
    # to short-circuit BEFORE that point.
    result = await generate_derivatives(
        mcp_name="bad_mcp",
        mcp_description="",
    )
    assert isinstance(result, GenerateResult)
    assert result.block_draft is None
    assert result.skill_draft is None
    assert any(i["severity"] == "error" for i in result.lint_issues)
    assert result.llm_model == ""  # never reached the LLM client


# ── PROMPT_VERSION sanity ────────────────────────────────────────────────────

def test_prompt_version_is_semver_ish():
    # Must be a non-empty string so it can be stored on the MCP audit meta.
    assert PROMPT_VERSION
    assert isinstance(PROMPT_VERSION, str)
