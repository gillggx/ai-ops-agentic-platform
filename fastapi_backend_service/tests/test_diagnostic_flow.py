"""Integration tests for the AI Diagnostic Agent.

Strategy
--------
All Anthropic API calls are **mocked** so the tests run without a real API key.
We verify:
1. ``BaseMCPSkill`` schema contract (JSON Schema format, both flavours).
2. Each skill's ``execute()`` returns the expected structure.
3. ``SKILL_REGISTRY`` contains all expected skills (including mcp_event_triage).
4. ``DiagnosticService.run()`` correctly orchestrates the agent loop.
5. ``POST /api/v1/diagnose/`` returns an SSE stream (text/event-stream).
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


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

import pytest
from httpx import AsyncClient

from app.schemas.diagnostic import DiagnoseRequest, DiagnoseResponse, ToolCallRecord
from app.skills import SKILL_REGISTRY
from app.skills.ask_user import AskUserRecentChangesSkill
from app.skills.base import BaseMCPSkill
from app.skills.etch_apc_check import EtchApcCheckSkill
from app.skills.etch_equipment_constants import EtchEquipmentConstantsSkill
from app.skills.etch_recipe_offset import EtchRecipeOffsetSkill

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers — build fake Anthropic response objects
# ---------------------------------------------------------------------------


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


def _make_response(
    stop_reason: str,
    blocks: list[MagicMock],
) -> MagicMock:
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = blocks
    return resp


# ---------------------------------------------------------------------------
# 1. BaseMCPSkill contract tests
# ---------------------------------------------------------------------------


class TestBaseMCPSkillContract:
    """Verify that each skill satisfies the BaseMCPSkill interface."""

    @pytest.mark.parametrize(
        "skill_cls",
        [EtchApcCheckSkill, EtchRecipeOffsetSkill, EtchEquipmentConstantsSkill, AskUserRecentChangesSkill],
    )
    def test_is_subclass(self, skill_cls: type) -> None:
        assert issubclass(skill_cls, BaseMCPSkill)

    @pytest.mark.parametrize(
        "skill_cls",
        [EtchApcCheckSkill, EtchRecipeOffsetSkill, EtchEquipmentConstantsSkill, AskUserRecentChangesSkill],
    )
    def test_anthropic_tool_schema(self, skill_cls: type) -> None:
        """to_anthropic_tool() must return name, description, input_schema."""
        skill = skill_cls()
        tool_def = skill.to_anthropic_tool()
        assert "name" in tool_def
        assert "description" in tool_def
        assert "input_schema" in tool_def
        assert tool_def["input_schema"]["type"] == "object"
        assert "properties" in tool_def["input_schema"]

    @pytest.mark.parametrize(
        "skill_cls",
        [EtchApcCheckSkill, EtchRecipeOffsetSkill, EtchEquipmentConstantsSkill, AskUserRecentChangesSkill],
    )
    def test_mcp_schema_camelcase(self, skill_cls: type) -> None:
        """to_mcp_schema() must use camelCase 'inputSchema' as per PRD."""
        skill = skill_cls()
        mcp = skill.to_mcp_schema()
        assert "inputSchema" in mcp
        assert "input_schema" not in mcp
        assert mcp["name"] == skill.name
        assert mcp["description"] == skill.description


# ---------------------------------------------------------------------------
# 2. Skill registry tests
# ---------------------------------------------------------------------------


class TestSkillRegistry:
    def test_registry_contains_all_skills(self) -> None:
        expected = {
            "mcp_event_triage",
            "mcp_check_recipe_offset",
            "mcp_check_equipment_constants",
            "mcp_check_apc_params",
            "ask_user_recent_changes",
        }
        assert expected.issubset(SKILL_REGISTRY.keys())

    def test_registry_values_are_skill_instances(self) -> None:
        for skill in SKILL_REGISTRY.values():
            assert isinstance(skill, BaseMCPSkill)

    def test_registry_keyed_by_name(self) -> None:
        for key, skill in SKILL_REGISTRY.items():
            assert key == skill.name


# ---------------------------------------------------------------------------
# 3. Individual skill execute() tests
# ---------------------------------------------------------------------------


class TestEtchApcCheckSkill:
    async def test_execute_returns_apc_data(self) -> None:
        skill = EtchApcCheckSkill()
        result = await skill.execute(target_equipment="EAP01", target_chamber="C1")
        assert result["equipment"] == "EAP01"
        assert result["chamber"] == "C1"
        assert "saturation_flag" in result
        assert "apc_model_status" in result

    async def test_execute_saturation_scenario(self) -> None:
        skill = EtchApcCheckSkill()
        result = await skill.execute(target_equipment="EAP01", target_chamber="C1")
        # Mock always returns SATURATED scenario
        assert result["saturation_flag"] is True
        assert result["apc_model_status"] == "SATURATED"

    async def test_execute_extra_kwargs_ignored(self) -> None:
        skill = EtchApcCheckSkill()
        result = await skill.execute(target_equipment="EAP02", target_chamber="PM1", extra="ignored")
        assert result["equipment"] == "EAP02"


class TestEtchRecipeOffsetSkill:
    async def test_execute_returns_recipe_data(self) -> None:
        skill = EtchRecipeOffsetSkill()
        result = await skill.execute(recipe_id="ETCH_CD_V3", equipment_id="EAP01")
        assert result["recipe_id"] == "ETCH_CD_V3"
        assert result["equipment_id"] == "EAP01"
        assert "has_human_modification" in result
        assert "version_match" in result

    async def test_execute_no_modification_scenario(self) -> None:
        skill = EtchRecipeOffsetSkill()
        result = await skill.execute(recipe_id="ETCH_CD_V3", equipment_id="EAP01")
        # Mock always returns no human modification
        assert result["has_human_modification"] is False
        assert result["version_match"] is True


class TestEtchEquipmentConstantsSkill:
    async def test_execute_returns_ec_data(self) -> None:
        skill = EtchEquipmentConstantsSkill()
        result = await skill.execute(eqp_name="EAP01", chamber_name="C1")
        assert result["eqp_name"] == "EAP01"
        assert result["chamber_name"] == "C1"
        assert "ec_comparison" in result
        assert "hardware_aging_risk" in result

    async def test_execute_low_risk_scenario(self) -> None:
        skill = EtchEquipmentConstantsSkill()
        result = await skill.execute(eqp_name="EAP01", chamber_name="C1")
        # Mock always returns LOW risk
        assert result["hardware_aging_risk"] == "LOW"
        assert result["out_of_spec_count"] == 0

    async def test_execute_ec_comparison_has_five_params(self) -> None:
        skill = EtchEquipmentConstantsSkill()
        result = await skill.execute(eqp_name="EAP01", chamber_name="C1")
        assert len(result["ec_comparison"]) == 5


class TestAskUserSkill:
    async def test_execute_known_topic(self) -> None:
        skill = AskUserRecentChangesSkill()
        result = await skill.execute(topic="deployment")
        assert "question_for_user" in result
        assert "deployment" in result["question_for_user"] or "部署" in result["question_for_user"]

    async def test_execute_unknown_topic_fallback(self) -> None:
        skill = AskUserRecentChangesSkill()
        result = await skill.execute(topic="network")
        assert "question_for_user" in result
        assert "network" in result["question_for_user"]

    async def test_execute_custom_time_window(self) -> None:
        skill = AskUserRecentChangesSkill()
        result = await skill.execute(topic="config", time_window="過去 1 週")
        assert "過去 1 週" in result["question_for_user"]


# ---------------------------------------------------------------------------
# 4. DiagnosticService agent loop tests (Anthropic client mocked)
# ---------------------------------------------------------------------------


class TestDiagnosticServiceLoop:
    """Verify the agent loop orchestration without hitting the real API."""

    async def _run_service(self, side_effects: list) -> DiagnoseResponse:
        """Helper: patch AsyncAnthropic and run the service."""
        from app.services.diagnostic_service import DiagnosticService

        with patch("app.services.diagnostic_service.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(side_effect=side_effects)

            service = DiagnosticService(max_turns=10)
            return await service.run("機台 EAP01 C1 發生 AEI CD 異常，連續 3 批 OOC")

    async def test_single_turn_no_tool_use(self) -> None:
        """Agent ends immediately on end_turn without calling any tools."""
        final_resp = _make_response(
            "end_turn",
            [_make_text_block("## 診斷報告\n無需工具呼叫。")],
        )
        result = await self._run_service([final_resp])

        assert result.total_turns == 1
        assert result.tools_invoked == []
        assert "診斷報告" in result.diagnosis_report

    async def test_triage_then_apc_then_end(self) -> None:
        """Agent calls triage → recipe_offset → equipment_constants → apc_params → end."""
        triage_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "mcp_event_triage",
                    "tu_triage_001",
                    {"user_symptom": "機台 EAP01 C1 發生 AEI CD 異常，連續 3 批 OOC"},
                ),
            ],
        )
        recipe_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "mcp_check_recipe_offset",
                    "tu_recipe_001",
                    {"recipe_id": "ETCH_CD_V3", "equipment_id": "EAP01"},
                ),
            ],
        )
        ec_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "mcp_check_equipment_constants",
                    "tu_ec_001",
                    {"eqp_name": "EAP01", "chamber_name": "C1"},
                ),
            ],
        )
        apc_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "mcp_check_apc_params",
                    "tu_apc_001",
                    {"target_equipment": "EAP01", "target_chamber": "C1"},
                ),
            ],
        )
        final_resp = _make_response(
            "end_turn",
            [_make_text_block("## 診斷報告\nAPC 飽和，建議 Chamber Wet Clean。")],
        )
        result = await self._run_service([triage_resp, recipe_resp, ec_resp, apc_resp, final_resp])

        assert result.total_turns == 5
        assert len(result.tools_invoked) == 4
        assert result.tools_invoked[0].tool_name == "mcp_event_triage"
        assert result.tools_invoked[1].tool_name == "mcp_check_recipe_offset"
        assert result.tools_invoked[2].tool_name == "mcp_check_equipment_constants"
        assert result.tools_invoked[3].tool_name == "mcp_check_apc_params"
        assert "Wet Clean" in result.diagnosis_report or "診斷報告" in result.diagnosis_report

    async def test_unknown_tool_is_handled_gracefully(self) -> None:
        """Agent requests an unknown tool — loop continues without crashing."""
        unknown_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "non_existent_tool",
                    "tu_unk_001",
                    {"foo": "bar"},
                ),
            ],
        )
        final_resp = _make_response(
            "end_turn",
            [_make_text_block("## 診斷報告\n工具不存在，仍完成診斷。")],
        )
        result = await self._run_service([unknown_resp, final_resp])

        # Unknown tools do NOT appear in tools_invoked
        assert all(r.tool_name != "non_existent_tool" for r in result.tools_invoked)
        assert result.diagnosis_report != ""

    async def test_ask_user_skill_recorded(self) -> None:
        """ask_user_recent_changes call is correctly recorded."""
        ask_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "ask_user_recent_changes",
                    "tu_ask_001",
                    {"topic": "deployment", "time_window": "過去 24 小時"},
                ),
            ],
        )
        final_resp = _make_response(
            "end_turn",
            [_make_text_block("## 診斷報告\n已詢問使用者部署變更。")],
        )
        result = await self._run_service([ask_resp, final_resp])

        assert len(result.tools_invoked) == 1
        assert result.tools_invoked[0].tool_name == "ask_user_recent_changes"
        assert "question_for_user" in result.tools_invoked[0].tool_result


# ---------------------------------------------------------------------------
# 5. HTTP endpoint integration tests
# ---------------------------------------------------------------------------


class TestDiagnoseEndpoint:
    """Verify the POST /api/v1/diagnose endpoint behaviour via the test client."""

    async def test_diagnose_unauthorized(self, client: AsyncClient) -> None:
        """Missing JWT → HTTP 401."""
        response = await client.post(
            "/api/v1/diagnose/",
            json={"issue_description": "系統有點慢"},
        )
        assert response.status_code == 401

    async def test_diagnose_short_description_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Description shorter than min_length (5) → HTTP 422."""
        response = await client.post(
            "/api/v1/diagnose/",
            json={"issue_description": "hi"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_diagnose_success_with_mocked_llm(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Happy-path: mocked LLM returns end_turn immediately → HTTP 200 SSE."""
        final_resp = _make_response(
            "end_turn",
            [_make_text_block("## 診斷報告\n系統正常，無異常。")],
        )

        with patch("app.services.diagnostic_service.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(return_value=final_resp)

            response = await client.post(
                "/api/v1/diagnose/",
                json={"issue_description": "機台 EAP01 發生 AEI CD 異常"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = _parse_sse_text(response.text)
        types = [e["type"] for e in events]
        assert "session_start" in types
        assert "report" in types
        assert "done" in types

        report_event = next(e for e in events if e["type"] == "report")
        assert "診斷報告" in report_event["data"]["content"]
        assert report_event["data"]["total_turns"] >= 1

    async def test_diagnose_with_tool_calls_mocked(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Mocked agent that invokes triage emits correct SSE records."""
        triage_resp = _make_response(
            "tool_use",
            [
                _make_tool_use_block(
                    "mcp_event_triage",
                    "tu_triage_http_001",
                    {"user_symptom": "機台 EAP01 C1 AEI CD 偏高"},
                ),
            ],
        )
        final_resp = _make_response(
            "end_turn",
            [_make_text_block("## 診斷報告\n已分診為 SPC_OOC_Etch_CD 事件。")],
        )

        with patch("app.services.diagnostic_service.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(side_effect=[triage_resp, final_resp])

            response = await client.post(
                "/api/v1/diagnose/",
                json={"issue_description": "機台 EAP01 C1 AEI CD 偏高"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        events = _parse_sse_text(response.text)
        tool_call_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_call_events) == 1
        assert tool_call_events[0]["data"]["tool_name"] == "mcp_event_triage"
