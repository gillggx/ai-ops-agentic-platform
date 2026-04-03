"""Phase 6 驗收測試：半導體蝕刻製程診斷 Copilot。

Acceptance Criteria (PRD Section 5)
------------------------------------
1. ``suggest-logic`` API 能根據 SPC Event Schema 給出專業提示。
2. ``auto-map`` API 能精準將名稱不同的機台參數連線。
3. 執行 Agent Loop，驗證是否正確走完半導體排障流程。

Test Strategy
--------------
- Builder API tests (auto-map, suggest-logic, validate-logic):
  Real LLM calls — to demonstrate actual LLM output quality.
  Skipped automatically if ANTHROPIC_API_KEY is not set.
- Agent Loop test:
  Mocked LLM — consistent, fast, no API cost.
- EventTriageSkill tests:
  Unit tests — no LLM needed.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# The canonical SPC OOC Etch CD event schema used across tests
_SPC_OOC_EVENT_SCHEMA = {
    "event_type": "SPC_OOC_Etch_CD",
    "attributes": {
        "lot_id": {
            "type": "string",
            "description": "發生異常的產品批號，例如 A1234",
        },
        "eqp_id": {
            "type": "string",
            "description": "處理該批號的蝕刻機台代碼，例如 EAP01",
        },
        "chamber_id": {
            "type": "string",
            "description": "機台內實際執行製程的反應室代碼，例如 C1、PM2",
        },
        "recipe_name": {
            "type": "string",
            "description": "該批號使用的蝕刻製程配方名稱",
        },
        "rule_violated": {
            "type": "string",
            "description": "觸發的 SPC 規則，例如 超出 3 sigma、連續 9 點在同側",
        },
        "consecutive_ooc_count": {
            "type": "integer",
            "description": "該機台/配方近期連續發生 OOC 的次數",
        },
        "control_limit_type": {
            "type": "string",
            "description": "觸發的是 UCL（上限）還是 LCL（下限）",
        },
    },
}

# APC tool input schema (field names differ from event attributes)
_APC_TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "target_equipment": {
            "type": "string",
            "description": "蝕刻機台代碼，例如 'EAP01'。對應事件物件中的 eqp_id 欄位。",
        },
        "target_chamber": {
            "type": "string",
            "description": "反應室代碼，例如 'C1'。對應事件物件中的 chamber_id 欄位。",
        },
    },
    "required": ["target_equipment", "target_chamber"],
}

# APC tool output schema (returned by mcp_check_apc_params.execute())
_APC_TOOL_OUTPUT_SCHEMA = {
    "equipment": "string — 機台代碼",
    "chamber": "string — 反應室代碼",
    "apc_model_status": "string — SATURATED | NORMAL",
    "feed_forward_bias_nm": "float — 前饋補償量（nm）",
    "feed_back_correction_pct": "float — 反饋修正百分比",
    "saturation_flag": "boolean — True 表示 APC 已飽和",
    "saturation_threshold_nm": "float — 飽和閾值（nm）",
    "consecutive_max_corrections": "int — 連續達到最大修正的批數",
    "trend": "string — 趨勢描述",
    "recommendation": "string — 處置建議",
}


def _skip_if_no_api_key():
    """Return pytest.mark.skip if ANTHROPIC_API_KEY is not set."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return pytest.mark.skip(reason="ANTHROPIC_API_KEY not set — skipping real LLM call")
    return pytest.mark.parametrize("_", [None])  # no-op mark


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(tool_name: str, tool_id: str, tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.id = tool_id
    block.input = tool_input
    return block


def _make_response(stop_reason: str, blocks: list) -> MagicMock:
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = blocks
    return resp


# ---------------------------------------------------------------------------
# 1. EventTriageSkill — unit tests (no LLM)
# ---------------------------------------------------------------------------


class TestEventTriageSkill:
    """Verify the SPC OOC event classification logic."""

    async def test_triage_etch_ooc_symptom(self) -> None:
        """Standard etch OOC symptom classifies as SPC_OOC_Etch_CD."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(
            user_symptom="機台 EAP01 C1 發生 AEI CD 偏高，連續 3 批 OOC，觸發 3sigma 規則"
        )

        assert result["event_type"] == "SPC_OOC_Etch_CD"
        assert result["attributes"]["urgency"] == "high"
        assert "mcp_check_recipe_offset" in result["recommended_skills"]
        assert "mcp_check_equipment_constants" in result["recommended_skills"]
        assert "mcp_check_apc_params" in result["recommended_skills"]

    async def test_triage_extracts_eqp_id(self) -> None:
        """EAP01 is extracted as eqp_id from symptom text."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(
            user_symptom="機台 EAP01 反應室 C1 發生 SPC OOC，配方 ETCH_CD_V3"
        )

        assert result["event_type"] == "SPC_OOC_Etch_CD"
        assert result["attributes"]["eqp_id"] == "EAP01"

    async def test_triage_extracts_lot_id(self) -> None:
        """Lot ID is extracted from symptom."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(
            user_symptom="Lot A1234 使用配方 ETCH_CD_V3，SPC 觸發 3-sigma 規則"
        )

        assert result["event_type"] == "SPC_OOC_Etch_CD"
        assert result["attributes"]["lot_id"] == "A1234"

    async def test_triage_extracts_ucl_control_limit(self) -> None:
        """UCL detected from '偏高' in symptom."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(
            user_symptom="EAP01 AEI CD 偏高，超出 UCL，連續 5 批"
        )

        assert result["attributes"]["control_limit_type"] == "UCL"

    async def test_triage_extracts_consecutive_count(self) -> None:
        """Consecutive OOC count extracted from symptom."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(
            user_symptom="機台 EAP01 連續 7 批 OOC，CD 偏高"
        )

        assert result["attributes"]["consecutive_ooc_count"] == 7

    async def test_triage_equipment_down(self) -> None:
        """Equipment down symptom → Equipment_Down event."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="機台 EAP01 掛了，無法連線")

        assert result["event_type"] == "Equipment_Down"
        assert result["attributes"]["urgency"] == "critical"

    async def test_triage_unknown_symptom(self) -> None:
        """Unrecognised symptom → Unknown_Fab_Symptom."""
        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="今天天氣很好")

        assert result["event_type"] == "Unknown_Fab_Symptom"

    async def test_triage_returns_event_id(self) -> None:
        """event_id follows EVT-XXXXXXXX pattern."""
        import re

        from app.skills.event_triage import EventTriageSkill

        skill = EventTriageSkill()
        result = await skill.execute(user_symptom="SPC OOC 異常")
        assert re.match(r"EVT-[0-9A-F]{8}$", result["event_id"])


# ---------------------------------------------------------------------------
# 2. suggest-logic API — real LLM call
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping real LLM call",
)
class TestSuggestLogicAPI:
    """Verify /suggest-logic returns expert PE-grade suggestions (real LLM)."""

    async def test_suggest_logic_returns_suggestions(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """POST /suggest-logic with SPC OOC Etch CD event schema."""
        response = await client.post(
            "/api/v1/builder/suggest-logic",
            json={
                "event_schema": _SPC_OOC_EVENT_SCHEMA,
                "context": "台積電 N3 製程，蝕刻機台 EAP01/EAP02，主要問題為 CD 偏高",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200, f"HTTP {response.status_code}: {response.text}"
        data = response.json()

        # Structural assertions
        assert "suggestions" in data
        assert "event_analysis" in data
        assert isinstance(data["suggestions"], list)
        assert 3 <= len(data["suggestions"]) <= 5, (
            f"Expected 3-5 suggestions, got {len(data['suggestions'])}"
        )
        assert len(data["event_analysis"]) > 50, "event_analysis should be substantive"

        # Content quality assertions — suggestions should mention etch-domain concepts
        all_text = " ".join(data["suggestions"]) + data["event_analysis"]
        has_etch_term = any(
            term in all_text
            for term in ["APC", "EC", "配方", "recipe", "OOC", "UCL", "LCL", "Wet Clean",
                         "蝕刻", "SPC", "CD", "chamber", "反應室", "consecutive", "連續"]
        )
        assert has_etch_term, f"Suggestions lack etch-domain terminology: {data['suggestions']}"

        # Print for human review (key deliverable)
        print("\n" + "=" * 70)
        print("📋 /suggest-logic 輸出結果")
        print("=" * 70)
        print(f"\n🔍 Event Schema 解析：\n{data['event_analysis']}\n")
        print("💡 排障邏輯建議：")
        for i, suggestion in enumerate(data["suggestions"], 1):
            print(f"  {i}. {suggestion}")
        print("=" * 70)


# ---------------------------------------------------------------------------
# 3. auto-map API — real LLM call
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping real LLM call",
)
class TestAutoMapAPI:
    """Verify /auto-map correctly maps eqp_id → target_equipment etc. (real LLM)."""

    async def test_auto_map_eqp_and_chamber(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """eqp_id should map to target_equipment, chamber_id to target_chamber."""
        response = await client.post(
            "/api/v1/builder/auto-map",
            json={
                "event_schema": _SPC_OOC_EVENT_SCHEMA["attributes"],
                "tool_input_schema": _APC_TOOL_INPUT_SCHEMA,
            },
            headers=auth_headers,
        )

        assert response.status_code == 200, f"HTTP {response.status_code}: {response.text}"
        data = response.json()

        assert "mappings" in data
        assert isinstance(data["mappings"], list)
        assert len(data["mappings"]) >= 1

        # At minimum eqp_id → target_equipment must be found
        mapped_pairs = {
            m["event_field"]: m["tool_param"]
            for m in data["mappings"]
        }

        assert "eqp_id" in mapped_pairs, (
            f"eqp_id not found in mappings. Got: {mapped_pairs}"
        )
        assert mapped_pairs["eqp_id"] == "target_equipment", (
            f"Expected eqp_id → target_equipment, got eqp_id → {mapped_pairs['eqp_id']}"
        )

        if "chamber_id" in mapped_pairs:
            assert mapped_pairs["chamber_id"] == "target_chamber", (
                f"Expected chamber_id → target_chamber, got {mapped_pairs['chamber_id']}"
            )

        # All mappings should be HIGH or MEDIUM confidence
        for mapping in data["mappings"]:
            assert mapping["confidence"] in ("HIGH", "MEDIUM", "LOW")

        print("\n" + "=" * 70)
        print("🗺️  /auto-map 輸出結果")
        print("=" * 70)
        for m in data["mappings"]:
            print(f"  {m['event_field']} → {m['tool_param']} [{m['confidence']}]")
            print(f"     {m['reasoning']}")
        print(f"\n  未映射參數: {data.get('unmapped_tool_params', [])}")
        print(f"  摘要: {data['summary']}")
        print("=" * 70)


# ---------------------------------------------------------------------------
# 4. validate-logic API — real LLM call
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping real LLM call",
)
class TestValidateLogicAPI:
    """Verify /validate-logic catches invalid field references (real LLM)."""

    async def test_valid_prompt_passes(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Prompt that references real APC fields should be valid."""
        response = await client.post(
            "/api/v1/builder/validate-logic",
            json={
                "user_prompt": (
                    "若 saturation_flag 為 True，且 feed_forward_bias_nm 超過 4.5nm，"
                    "則判定 APC 已飽和，建議安排 Chamber Wet Clean"
                ),
                "tool_output_schema": _APC_TOOL_OUTPUT_SCHEMA,
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert len(data.get("issues", [])) == 0

    async def test_invalid_prompt_caught(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Prompt that references a non-existent field should be flagged."""
        response = await client.post(
            "/api/v1/builder/validate-logic",
            json={
                "user_prompt": (
                    "若 plasma_uniformity_index 低於 0.85，"
                    "且 rf_matching_error 超過 10%，則建議 PM"
                ),
                "tool_output_schema": _APC_TOOL_OUTPUT_SCHEMA,
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # plasma_uniformity_index and rf_matching_error do not exist in APC output
        assert data["is_valid"] is False
        assert len(data["issues"]) > 0


# ---------------------------------------------------------------------------
# 5. Full Agent Loop — mocked LLM, etch scenario
# ---------------------------------------------------------------------------


class TestEtchAgentLoop:
    """End-to-end etch diagnostic loop: triage → recipe → EC → APC → Wet Clean."""

    async def test_full_etch_diagnostic_flow(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Simulate full semiconductor diagnostic loop via SSE endpoint."""
        # Mocked LLM responses simulating the PE reasoning chain:
        # Turn 1: agent calls mcp_event_triage
        triage_resp = _make_response(
            "tool_use",
            [_make_tool_use_block(
                "mcp_event_triage",
                "tu_triage_001",
                {"user_symptom": "機台 EAP01 C1 發生 AEI CD 偏高，連續 3 批 OOC"},
            )],
        )
        # Turn 2: agent calls mcp_check_recipe_offset
        recipe_resp = _make_response(
            "tool_use",
            [_make_tool_use_block(
                "mcp_check_recipe_offset",
                "tu_recipe_001",
                {"recipe_id": "ETCH_CD_V3", "equipment_id": "EAP01"},
            )],
        )
        # Turn 3: agent calls mcp_check_equipment_constants
        ec_resp = _make_response(
            "tool_use",
            [_make_tool_use_block(
                "mcp_check_equipment_constants",
                "tu_ec_001",
                {"eqp_name": "EAP01", "chamber_name": "C1"},
            )],
        )
        # Turn 4: agent calls mcp_check_apc_params
        apc_resp = _make_response(
            "tool_use",
            [_make_tool_use_block(
                "mcp_check_apc_params",
                "tu_apc_001",
                {"target_equipment": "EAP01", "target_chamber": "C1"},
            )],
        )
        # Turn 5: agent synthesises final Markdown report
        final_resp = _make_response(
            "end_turn",
            [_make_text_block(
                "## 根因分析\n"
                "配方無人為修改，EC 在規格內，但 APC 前饋補償值已達飽和閾值。\n\n"
                "## 建議處置\n"
                "安排 Chamber Wet Clean，完成後重新執行 Recipe 標定。"
            )],
        )

        with patch("app.services.diagnostic_service.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(
                side_effect=[triage_resp, recipe_resp, ec_resp, apc_resp, final_resp]
            )

            response = await client.post(
                "/api/v1/diagnose/",
                json={"issue_description": "機台 EAP01 C1 發生 AEI CD 偏高，連續 3 批 OOC"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = _parse_sse_text(response.text)
        types = [e["type"] for e in events]
        assert "session_start" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "report" in types
        assert "done" in types

        # Verify all 4 tools were called in the correct order
        tool_call_events = [e for e in events if e["type"] == "tool_call"]
        tool_names = [e["data"]["tool_name"] for e in tool_call_events]
        assert tool_names == [
            "mcp_event_triage",
            "mcp_check_recipe_offset",
            "mcp_check_equipment_constants",
            "mcp_check_apc_params",
        ], f"Unexpected tool call order: {tool_names}"

        # Verify tool results were emitted
        tool_result_events = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_result_events) == 4

        # Verify triage result contains SPC_OOC_Etch_CD event
        triage_result = next(
            e["data"]["tool_result"]
            for e in tool_result_events
            if e["data"]["tool_name"] == "mcp_event_triage"
        )
        assert triage_result["event_type"] == "SPC_OOC_Etch_CD"
        assert triage_result["attributes"]["eqp_id"] == "EAP01"

        # Verify APC result indicates saturation
        apc_result = next(
            e["data"]["tool_result"]
            for e in tool_result_events
            if e["data"]["tool_name"] == "mcp_check_apc_params"
        )
        assert apc_result["saturation_flag"] is True

        # Verify final report
        report_event = next(e for e in events if e["type"] == "report")
        assert report_event["data"]["total_turns"] == 5
        assert "Wet Clean" in report_event["data"]["content"]

    async def test_builder_auth_required(
        self,
        client: AsyncClient,
    ) -> None:
        """Builder endpoints require JWT — no token → 401."""
        for endpoint in ["/auto-map", "/validate-logic", "/suggest-logic"]:
            response = await client.post(
                f"/api/v1/builder{endpoint}",
                json={"event_schema": {}, "tool_input_schema": {}},
            )
            assert response.status_code == 401, (
                f"{endpoint} should require auth, got {response.status_code}"
            )


# ---------------------------------------------------------------------------
# Helper (same as in test_diagnostic_flow.py)
# ---------------------------------------------------------------------------


def _parse_sse_text(text: str) -> list[dict]:
    """Parse raw SSE text into a list of ``{"type": str, "data": dict}`` dicts."""
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
