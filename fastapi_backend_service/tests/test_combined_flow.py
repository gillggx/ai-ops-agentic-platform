"""Phase 3 Combined Integration Tests: SSE Streaming + All-in-MCP Triage.

Two mandatory verification objectives
--------------------------------------
(A) SSE 串流格式正確
    Every chunk yielded by ``DiagnosticService.stream()`` must conform to the
    RFC 8895 SSE format:  ``event: <type>\\ndata: <json>\\n\\n``.
    The HTTP endpoint must respond with ``Content-Type: text/event-stream``.

(B) 第一個被觸發的 Skill 確實是 mcp_event_triage
    The ``tool_call`` SSE event sequence must begin with
    ``{"tool_name": "mcp_event_triage", ...}``.

All Anthropic API calls are mocked — no real API key required.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.skills import SKILL_REGISTRY
from app.skills.event_triage import EventTriageSkill

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _parse_sse(text: str) -> list[dict]:
    """Parse raw SSE text into ``[{"type": str, "data": dict}, ...]``."""
    events = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        event_type = None
        data_str = None
        for line in chunk.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type and data_str:
            events.append({"type": event_type, "data": json.loads(data_str)})
    return events


# ---------------------------------------------------------------------------
# Mock Anthropic response builders
# ---------------------------------------------------------------------------


def _text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _tool_block(name: str, id_: str, input_: dict) -> MagicMock:
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.id = id_
    b.input = input_
    return b


def _response(stop_reason: str, blocks: list) -> MagicMock:
    r = MagicMock()
    r.stop_reason = stop_reason
    r.content = blocks
    return r


# ---------------------------------------------------------------------------
# 1. EventTriageSkill unit tests — verify Event Object output
# ---------------------------------------------------------------------------


class TestEventTriageSkill:
    """Directly exercise mcp_event_triage and print Event Objects."""

    async def test_performance_symptom_classification(self) -> None:
        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="系統很慢，CPU 使用率很高")

        print(f"\n[Event Object — Performance]\n{json.dumps(result, ensure_ascii=False, indent=2)}")

        assert result["event_type"] == "Performance_Degradation"
        assert result["event_id"].startswith("EVT-")
        assert len(result["event_id"]) == 12      # "EVT-" + 8 hex chars
        assert "mcp_mock_cpu_check" in result["recommended_skills"]
        assert result["attributes"]["urgency"] == "high"
        assert result["attributes"]["symptom"] == "系統很慢，CPU 使用率很高"

    async def test_memory_symptom_classification(self) -> None:
        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="memory leak detected, OOM kill")
        print(f"\n[Event Object — Memory]\n{json.dumps(result, ensure_ascii=False, indent=2)}")
        assert result["event_type"] == "Memory_Leak"

    async def test_service_down_classification(self) -> None:
        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="服務掛了，503 unavailable")
        print(f"\n[Event Object — ServiceDown]\n{json.dumps(result, ensure_ascii=False, indent=2)}")
        assert result["event_type"] == "Service_Down"
        assert result["attributes"]["urgency"] == "critical"

    async def test_unknown_symptom_fallback(self) -> None:
        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="我也不知道發生什麼事")
        print(f"\n[Event Object — Unknown]\n{json.dumps(result, ensure_ascii=False, indent=2)}")
        assert result["event_type"] == "Unknown_Symptom"
        assert result["recommended_skills"] == ["mcp_rag_knowledge_search"]

    async def test_event_object_has_required_keys(self) -> None:
        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="磁碟空間不足")
        required = {"event_id", "event_type", "attributes", "recommended_skills"}
        assert required == set(result.keys())

    def test_triage_is_first_in_registry(self) -> None:
        """mcp_event_triage must be the first key in SKILL_REGISTRY (insertion-ordered)."""
        first_name = next(iter(SKILL_REGISTRY))
        assert first_name == "mcp_event_triage", (
            f"Expected first skill to be 'mcp_event_triage', got '{first_name}'"
        )


# ---------------------------------------------------------------------------
# 2. DiagnosticService.stream() — SSE format + triage-first (A + B)
# ---------------------------------------------------------------------------


class TestDiagnosticServiceStream:
    """Verify the async generator produces correctly formatted SSE events."""

    async def _collect(self, side_effects: list) -> tuple[list[str], list[dict]]:
        """Run stream() and return (raw_chunks, parsed_events)."""
        from app.services.diagnostic_service import DiagnosticService

        with patch("app.services.diagnostic_service.anthropic.AsyncAnthropic") as MockCls:
            inst = AsyncMock()
            MockCls.return_value = inst
            inst.messages.create = AsyncMock(side_effect=side_effects)

            svc = DiagnosticService(max_turns=10)
            chunks: list[str] = []
            async for chunk in svc.stream("系統變好慢"):
                chunks.append(chunk)

        raw_text = "".join(chunks)
        return chunks, _parse_sse(raw_text)

    # ── (A) SSE FORMAT ──────────────────────────────────────────────────────

    async def test_A_every_chunk_starts_with_event_colon(self) -> None:
        """(A) Each raw SSE chunk must start with 'event: '."""
        final = _response("end_turn", [_text_block("## 報告")])
        chunks, _ = await self._collect([final])

        for chunk in chunks:
            assert chunk.startswith("event: "), (
                f"(A) FAILED: chunk does not start with 'event: '  →  {chunk!r}"
            )

    async def test_A_every_chunk_contains_data_line(self) -> None:
        """(A) Each raw SSE chunk must contain a 'data: ' line."""
        final = _response("end_turn", [_text_block("## 報告")])
        chunks, _ = await self._collect([final])

        for chunk in chunks:
            assert "\ndata: " in chunk, (
                f"(A) FAILED: chunk missing 'data: ' line  →  {chunk!r}"
            )

    async def test_A_every_chunk_ends_with_double_newline(self) -> None:
        """(A) Each raw SSE chunk must end with the mandatory double newline."""
        final = _response("end_turn", [_text_block("## 報告")])
        chunks, _ = await self._collect([final])

        for chunk in chunks:
            assert chunk.endswith("\n\n"), (
                f"(A) FAILED: chunk does not end with '\\n\\n'  →  {chunk!r}"
            )

    async def test_A_stream_starts_with_session_start(self) -> None:
        """(A) First SSE event must be 'session_start'."""
        final = _response("end_turn", [_text_block("## 報告")])
        _, events = await self._collect([final])
        assert events[0]["type"] == "session_start"

    async def test_A_stream_ends_with_done(self) -> None:
        """(A) Last SSE event must always be 'done'."""
        final = _response("end_turn", [_text_block("## 報告")])
        _, events = await self._collect([final])
        assert events[-1]["type"] == "done"
        assert events[-1]["data"]["status"] == "complete"

    async def test_A_report_event_contains_markdown(self) -> None:
        """(A) 'report' event must carry diagnosis content and metadata."""
        final = _response("end_turn", [_text_block("## 診斷報告\n建議水平擴展")])
        _, events = await self._collect([final])

        reports = [e for e in events if e["type"] == "report"]
        assert len(reports) == 1
        d = reports[0]["data"]
        assert "建議水平擴展" in d["content"]
        assert d["total_turns"] >= 1
        assert isinstance(d["tools_invoked"], list)

    # ── (B) TRIAGE FIRST ────────────────────────────────────────────────────

    async def test_B_triage_is_first_tool_call_event(self) -> None:
        """(B) The first 'tool_call' SSE event must name 'mcp_event_triage'."""
        triage = _response("tool_use", [
            _tool_block("mcp_event_triage", "tu_t_001", {"user_symptom": "系統很慢"}),
        ])
        cpu = _response("tool_use", [
            _tool_block("mcp_mock_cpu_check", "tu_c_001", {"service_name": "api-server"}),
        ])
        final = _response("end_turn", [_text_block("## 報告\nCPU 87%")])

        _, events = await self._collect([triage, cpu, final])

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        print(f"\n[tool_call sequence] {[e['data']['tool_name'] for e in tool_calls]}")

        assert len(tool_calls) >= 2, "Expected at least 2 tool_call events"
        first_tool = tool_calls[0]["data"]["tool_name"]
        assert first_tool == "mcp_event_triage", (
            f"(B) FAILED: first tool_call is '{first_tool}', expected 'mcp_event_triage'"
        )

    async def test_B_tool_result_follows_tool_call(self) -> None:
        """(B) Every 'tool_call' must be immediately followed by a 'tool_result'."""
        triage = _response("tool_use", [
            _tool_block("mcp_event_triage", "tu_t_002", {"user_symptom": "服務很慢"}),
        ])
        final = _response("end_turn", [_text_block("## 報告")])
        _, events = await self._collect([triage, final])

        types = [e["type"] for e in events]
        call_idx = types.index("tool_call")
        result_idx = types.index("tool_result")
        assert result_idx == call_idx + 1, (
            f"(B) tool_result must immediately follow tool_call, "
            f"got types={types}"
        )

    async def test_B_triage_event_object_in_tool_result(self) -> None:
        """(B) The tool_result for mcp_event_triage must contain a valid Event Object."""
        triage = _response("tool_use", [
            _tool_block("mcp_event_triage", "tu_t_003", {"user_symptom": "CPU 很高"}),
        ])
        final = _response("end_turn", [_text_block("## 報告")])
        _, events = await self._collect([triage, final])

        triage_results = [
            e for e in events
            if e["type"] == "tool_result" and e["data"]["tool_name"] == "mcp_event_triage"
        ]
        assert len(triage_results) == 1
        event_obj = triage_results[0]["data"]["tool_result"]

        print(f"\n[Event Object from stream]\n{json.dumps(event_obj, ensure_ascii=False, indent=2)}")

        assert "event_id" in event_obj
        assert "event_type" in event_obj
        assert "recommended_skills" in event_obj
        assert event_obj["event_id"].startswith("EVT-")


# ---------------------------------------------------------------------------
# 3. HTTP endpoint — combined (A) + (B) via test client
# ---------------------------------------------------------------------------


class TestDiagnoseSSEEndpoint:
    """Verify POST /api/v1/diagnose/ returns correct SSE with triage-first."""

    async def test_unauthorized_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/diagnose/",
            json={"issue_description": "系統有點慢"},
        )
        assert response.status_code == 401

    async def test_short_description_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/diagnose/",
            json={"issue_description": "hi"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_AB_sse_format_and_triage_first(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        """
        Combined (A) + (B) verification through the real HTTP endpoint.

        (A) Content-Type is text/event-stream; stream contains session_start,
            report, done events; each raw line follows SSE spec.
        (B) First tool_call event names mcp_event_triage.
        """
        triage_resp = _response("tool_use", [
            _tool_block("mcp_event_triage", "tu_t_http_001",
                        {"user_symptom": "系統 CPU 使用率突然飆升"}),
        ])
        final_resp = _response("end_turn", [
            _text_block("## 診斷報告\n已分診，建議查 CPU。"),
        ])

        with patch("app.services.diagnostic_service.anthropic.AsyncAnthropic") as MockCls:
            inst = AsyncMock()
            MockCls.return_value = inst
            inst.messages.create = AsyncMock(side_effect=[triage_resp, final_resp])

            response = await client.post(
                "/api/v1/diagnose/",
                json={"issue_description": "系統 CPU 使用率突然飆升"},
                headers=auth_headers,
            )

        # ── (A) HTTP-level checks ─────────────────────────────────────────
        assert response.status_code == 200
        ct = response.headers.get("content-type", "")
        assert "text/event-stream" in ct, f"(A) Expected text/event-stream, got: {ct}"

        events = _parse_sse(response.text)
        event_types = [e["type"] for e in events]
        print(f"\n[HTTP SSE event_types] {event_types}")

        assert "session_start" in event_types, "(A) Missing session_start"
        assert "report" in event_types,        "(A) Missing report"
        assert "done" in event_types,          "(A) Missing done"

        # ── (B) Triage-first check ────────────────────────────────────────
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) >= 1, "(B) No tool_call events found"

        first_tool = tool_calls[0]["data"]["tool_name"]
        print(f"[First tool called] {first_tool}")
        assert first_tool == "mcp_event_triage", (
            f"(B) FAILED: first tool is '{first_tool}', must be 'mcp_event_triage'"
        )
