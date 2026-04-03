"""DiagnosticRuleService — CRUD + two-phase streaming LLM generation for source='rule' skills."""

import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.diagnostic_rule import (
    DiagnosticRuleCreate,
    DiagnosticRuleResponse,
    DiagnosticRuleUpdate,
    GenerateRuleStepsRequest,
    GenerateRuleStepsResponse,
)

logger = logging.getLogger(__name__)

_SOURCE = "rule"

# Mock values used when sampling MCP responses during Phase 1.5
_MOCK_PARAMS: Dict[str, Any] = {
    "equipment_id": "EQP-01",
    "toolID": "EQP-01",
    "lot_id": "LOT-0001",
    "lotID": "LOT-0001",
    "step": "STEP_038",
    "objectName": "APC",
    "limit": 3,
}

# Fallback samples shown to Phase 2 LLM when real MCP calls return empty data
# Gives the LLM concrete field names to write correct code against
_FALLBACK_SAMPLES: Dict[str, Any] = {
    "get_process_history": [
        {"eventTime": "2026-03-15T06:10:00", "lotID": "LOT-0007", "toolID": "EQP-01",
         "step": "STEP_045", "recipeID": "RCP-007", "spc_status": "OOC", "apcID": "APC-045"},
        {"eventTime": "2026-03-15T05:50:00", "lotID": "LOT-0006", "toolID": "EQP-01",
         "step": "STEP_045", "recipeID": "RCP-007", "spc_status": "PASS", "apcID": "APC-044"},
    ],
    "get_process_context": {
        "SPC": {"spc_status": "OOC", "charts": {"xbar_chart": {"value": 18.1, "ucl": 17.5, "lcl": 12.5}}},
        "APC": {"parameters": {"etch_time_offset": {"value": 0.042}, "etch_time_s": {"value": 30.5}}},
        "DC":  {"parameters": {"chamber_pressure": {"value": 15.2, "usl": 18.0, "lsl": 12.0},
                                "gas_flow": {"value": 200.1, "usl": 220.0, "lsl": 180.0}}},
        "RECIPE": {"parameters": {"etch_time_s": {"value": 30.0}, "pressure": {"value": 15.0}}},
    },
}

# Compact MCP catalog for Phase 1 — only names, purposes, return shapes
_MCP_CATALOG_BRIEF = (
    "Available MCPs (use ONLY these):\n"
    "\n"
    "- get_process_history  params: toolID(opt), lotID(opt), limit(opt, default 10)\n"
    "  回傳: [{eventTime, lotID, toolID, step, recipeID, spc_status:'PASS'|'OOC'|null, apcID}]\n"
    "  用途: 查機台/批次最近 N 次製程清單、recipe check、OOC trend\n"
    "\n"
    "- get_process_context  params: targetID(required), step(required), objectName(required)\n"
    "  objectName choices: SPC / DC / APC / RECIPE / EC\n"
    "  SPC 回傳: {charts: {xbar_chart: {value, ucl, lcl}}, spc_status}\n"
    "  APC 回傳: {parameters: {<param_name>: {value}}}\n"
    "  DC  回傳: {parameters: {<sensor_name>: {value, usl, lsl}}}\n"
    "  用途: 取某批次+步驟的物件詳細數值（需先從 get_process_history 取得 lotID + step）\n"
)

_OUTPUT_SCHEMA_GUIDE = """\
OUTPUT SCHEMA TYPES — pick the most appropriate type for each output field:
  scalar        → {"key": "ooc_count",   "type": "scalar",       "label": "OOC次數",    "unit": "次"}
  table         → {"key": "records",     "type": "table",        "label": "記錄",       "columns": [{"key": "value","label":"量測值","type":"float"}, ...]}
  badge         → {"key": "status",      "type": "badge",        "label": "診斷結論"}
  line_chart    → {"key": "spc_trend",   "type": "line_chart",   "label": "SPC管制圖",  "x_key": "index", "y_keys": ["value","ucl","lcl"], "highlight_key": "is_ooc"}
  bar_chart     → {"key": "ooc_by_tool", "type": "bar_chart",    "label": "各機台OOC次數", "x_key": "tool", "y_keys": ["ooc_count"]}
  scatter_chart → {"key": "correlation", "type": "scatter_chart","label": "相關性",     "x_key": "param_a", "y_keys": ["param_b"]}

Chart data in _findings.outputs must be a list of dicts matching x_key + y_keys.
RULE: When user description mentions 圖/chart/trend/趨勢/管制圖/分佈, you MUST include the matching chart type in output_schema."""


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(obj) -> DiagnosticRuleResponse:
    def _j(s):
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    return DiagnosticRuleResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        auto_check_description=obj.auto_check_description or "",
        steps_mapping=_j(obj.steps_mapping),
        input_schema=_j(obj.input_schema) if hasattr(obj, "input_schema") else [],
        output_schema=_j(obj.output_schema),
        visibility=obj.visibility,
        is_active=obj.is_active,
        source=obj.source,
        created_by=obj.created_by,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        trigger_patrol_id=getattr(obj, "trigger_patrol_id", None),
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _shape_str(data: Any) -> str:
    """Compact shape description for console display."""
    if isinstance(data, list):
        if not data:
            return "[]"
        first = data[0]
        if isinstance(first, dict):
            keys = list(first.keys())
            shown = ", ".join(keys[:5])
            suffix = ", ..." if len(keys) > 5 else ""
            return f"[{{{shown}{suffix}}}, ...]"
        return f"list[{len(data)}]"
    elif isinstance(data, dict):
        keys = list(data.keys())
        shown = ", ".join(keys[:5])
        suffix = ", ..." if len(keys) > 5 else ""
        return f"{{{shown}{suffix}}}"
    return type(data).__name__


def _resolve_mock_params(params_template: dict) -> dict:
    """Replace {placeholder} string values with mock values for sample fetching."""
    result = {}
    for k, v in params_template.items():
        if isinstance(v, str) and v.startswith("{") and v.endswith("}") and len(v) > 2:
            placeholder = v[1:-1]
            result[k] = _MOCK_PARAMS.get(placeholder, v)
        else:
            result[k] = v
    return result


# ── Service ────────────────────────────────────────────────────────────────────


class DiagnosticRuleService:
    def __init__(
        self,
        repo: SkillDefinitionRepository,
        db: AsyncSession,
        llm=None,
    ) -> None:
        self._repo = repo
        self._db = db
        self._llm = llm

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def list_all(self) -> List[DiagnosticRuleResponse]:
        objs = await self._repo.list_by_source(_SOURCE)
        return [_to_response(o) for o in objs]

    async def get(self, rule_id: int) -> DiagnosticRuleResponse:
        obj = await self._repo.get_by_id(rule_id)
        if not obj or obj.source != _SOURCE:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Rule id={rule_id} 不存在")
        return _to_response(obj)

    async def create(
        self,
        body: DiagnosticRuleCreate,
        created_by: Optional[int] = None,
    ) -> DiagnosticRuleResponse:
        data = body.model_dump()
        data["source"] = _SOURCE
        data["trigger_mode"] = "event"
        data["created_by"] = created_by
        obj = await self._repo.create(data)
        return _to_response(obj)

    async def update(self, rule_id: int, body: DiagnosticRuleUpdate) -> DiagnosticRuleResponse:
        obj = await self._repo.get_by_id(rule_id)
        if not obj or obj.source != _SOURCE:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Rule id={rule_id} 不存在")
        data = body.model_dump(exclude_none=True)
        updated = await self._repo.update(rule_id, data)
        return _to_response(updated)

    async def delete(self, rule_id: int) -> None:
        obj = await self._repo.get_by_id(rule_id)
        if not obj or obj.source != _SOURCE:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Rule id={rule_id} 不存在")
        await self._repo.delete(rule_id)

    # ── LLM Generation — Two-Phase Streaming ──────────────────────────────────

    async def generate_steps_stream(
        self, body: GenerateRuleStepsRequest
    ) -> AsyncGenerator[str, None]:
        """Streams SSE events for two-phase DR generation.

        Phase 1  — LLM decides which MCPs are needed
        Phase 1.5 — Backend samples each MCP with mock params
        Phase 2  — LLM writes analysis code given confirmed MCPs + real response shapes
        """
        if not self._llm:
            yield _sse({"type": "error", "error": "LLM service not configured"})
            return

        # ── Phase 1: MCP Planner ──────────────────────────────────────────────
        yield _sse({"type": "phase", "phase": 1, "message": "分析需求，規劃資料來源..."})

        try:
            plan = await self._plan_mcps(body.auto_check_description)
        except Exception as exc:
            logger.warning("DR Phase 1 failed: %s", exc)
            yield _sse({"type": "error", "error": f"Phase 1 失敗: {exc}"})
            return

        mcp_calls: List[dict] = plan.get("mcp_calls", [])[:5]
        reasoning: str = plan.get("reasoning", "")

        yield _sse({"type": "mcp_plan", "reasoning": reasoning, "mcp_calls": mcp_calls})
        for mc in mcp_calls:
            yield _sse({"type": "log", "message": f"→ {mc['mcp_name']}  {mc.get('purpose', '')}"})

        # ── Phase 1.5: Sample MCP responses ──────────────────────────────────
        yield _sse({"type": "phase", "phase": 1.5, "message": "擷取資料結構..."})

        from app.config import get_settings
        from app.services.skill_executor_service import build_mcp_executor
        settings = get_settings()
        mcp_executor = build_mcp_executor(self._db, sim_url=settings.ONTOLOGY_SIM_URL)

        sample_responses: Dict[str, Any] = {}
        for mc in mcp_calls:
            mcp_name = mc["mcp_name"]
            yield _sse({"type": "fetch", "mcp_name": mcp_name, "status": "fetching"})
            try:
                mock_params = _resolve_mock_params(mc.get("params_template", {}))
                result = await mcp_executor(mcp_name, mock_params)
                shape = _shape_str(result)
                sample_responses[mcp_name] = result
                yield _sse({"type": "fetch", "mcp_name": mcp_name, "status": "ok", "shape": shape})
            except Exception as exc:
                logger.warning("DR Phase 1.5 MCP '%s' failed: %s", mcp_name, exc)
                sample_responses[mcp_name] = {}
                yield _sse({"type": "fetch", "mcp_name": mcp_name, "status": "error", "error": str(exc)})

        # ── Phase 2: Code Generator ───────────────────────────────────────────
        yield _sse({"type": "phase", "phase": 2, "message": "生成分析邏輯..."})

        try:
            parsed = await self._generate_code(
                body.auto_check_description, mcp_calls, sample_responses
            )
            steps = parsed.get("steps_mapping", [])
            proposal = parsed.get("proposal_steps", [s.get("nl_segment", "") for s in steps])
            yield _sse({
                "type": "done",
                "result": {
                    "proposal_steps": proposal,
                    "steps_mapping": steps,
                    "input_schema": parsed.get("input_schema", []),
                    "output_schema": parsed.get("output_schema", []),
                },
            })
        except Exception as exc:
            logger.warning("DR Phase 2 failed: %s", exc)
            yield _sse({"type": "error", "error": f"Phase 2 失敗: {exc}"})

    async def generate_steps(self, body: GenerateRuleStepsRequest) -> GenerateRuleStepsResponse:
        """Non-streaming wrapper — collects stream events and returns final result."""
        last_error: Optional[str] = None
        async for raw in self.generate_steps_stream(body):
            if not raw.startswith("data: "):
                continue
            try:
                event = json.loads(raw[6:])
            except Exception:
                continue
            if event.get("type") == "done":
                r = event["result"]
                return GenerateRuleStepsResponse(
                    success=True,
                    proposal_steps=r.get("proposal_steps", []),
                    steps_mapping=r.get("steps_mapping", []),
                    input_schema=r.get("input_schema", []),
                    output_schema=r.get("output_schema", []),
                )
            if event.get("type") == "error":
                last_error = event.get("error", "LLM 生成失敗")
        return GenerateRuleStepsResponse(success=False, error=last_error or "LLM 生成失敗")

    # ── Private: Phase 1 — MCP Planner ────────────────────────────────────────

    async def _plan_mcps(self, description: str) -> dict:
        system_prompt = f"""\
You are a factory AI data planning expert.
Given a diagnostic rule description, decide which MCPs are needed and in what order.
Output ONLY valid JSON. No explanation, no markdown fences.

{_MCP_CATALOG_BRIEF}
Rules:
- Only use MCPs from the list above
- Max 5 MCP calls
- params_template: dynamic values use {{variable_name}} format (e.g. {{{{equipment_id}}}}, {{{{lot_id}}}}, {{{{step}}}})
- List in execution order

Required output format:
{{
  "reasoning": "brief explanation of what data is needed and why",
  "mcp_calls": [
    {{"mcp_name": "get_process_history", "purpose": "取機台最近10次製程清單", "params_template": {{"toolID": "{{{{equipment_id}}}}", "limit": 10}}}},
    {{"mcp_name": "get_process_context", "purpose": "取每筆製程的APC參數", "params_template": {{"targetID": "{{{{lot_id}}}}", "step": "{{{{step}}}}", "objectName": "APC"}}}}
  ]
}}"""

        resp = await self._llm.create(
            system=system_prompt,
            messages=[{"role": "user", "content": f"Diagnostic rule description:\n{description}"}],
            max_tokens=1024,
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.text.strip(), flags=re.MULTILINE).strip()
        return json.loads(raw)

    # ── Private: Phase 2 — Code Generator ─────────────────────────────────────

    async def _generate_code(
        self,
        description: str,
        mcp_calls: List[dict],
        sample_responses: Dict[str, Any],
    ) -> dict:
        # Build confirmed MCP section with actual (or fallback) sample data
        # so LLM knows exact field names and can write correct code
        confirmed_section = "Confirmed MCPs to use (execute in this order):\n"
        for i, mc in enumerate(mcp_calls, 1):
            mcp_name = mc["mcp_name"]
            purpose = mc.get("purpose", "")
            tmpl = mc.get("params_template", {})

            # Prefer real sample; fall back to static example when sim returned empty
            sample = sample_responses.get(mcp_name)
            if not sample:
                # pick the right fallback key for get_process_context based on objectName
                if mcp_name == "get_process_context":
                    obj_name = tmpl.get("objectName", "SPC")
                    fb = _FALLBACK_SAMPLES.get("get_process_context", {})
                    sample = fb.get(obj_name) or fb.get("SPC")
                else:
                    sample = _FALLBACK_SAMPLES.get(mcp_name)

            sample_str = ""
            if sample:
                preview = sample[:2] if isinstance(sample, list) else sample
                note = "  ← fallback example (simulator had no data)" if not sample_responses.get(mcp_name) else ""
                sample_str = f"\n   Sample response{note}: {json.dumps(preview, ensure_ascii=False)[:500]}"

            confirmed_section += (
                f"{i}. execute_mcp('{mcp_name}', {json.dumps(tmpl, ensure_ascii=False)})\n"
                f"   Purpose: {purpose}{sample_str}\n"
            )

        system_prompt = f"""\
You are a factory AI monitoring expert. Convert natural language diagnostic logic into structured Python steps.
CRITICAL: Output ONLY a valid JSON object. No explanation, no markdown fences, nothing outside JSON.

{confirmed_section}
Special functions (call only, no import):
- await execute_mcp(mcp_name: str, params: dict) -> Any

Forbidden: import, open(), exec(), eval(), os, sys, subprocess, trigger_alarm

INPUT: The skill receives a dict. Access keys like: equipment_id = _input.get("equipment_id")
Also available as top-level vars: equipment_id, lot_id, step, event_time

OUTPUT: The LAST step MUST assign _findings:
_findings = {{
    "condition_met": <bool>,
    "summary": "<one sentence conclusion>",
    "outputs": {{"<output_schema key>": <value>, ...}},
    "impacted_lots": [<lot_id>] if condition_met else []
}}

{_OUTPUT_SCHEMA_GUIDE}

Required output format (JSON only):
{{
  "proposal_steps": ["Plain English step 1", "Plain English step 2"],
  "steps_mapping": [
    {{"step_id": "step1", "nl_segment": "...", "python_code": "..."}}
  ],
  "input_schema": [
    {{"key": "equipment_id", "type": "string", "required": true, "description": "目標機台 ID"}}
  ],
  "output_schema": [
    {{"key": "ooc_count", "type": "scalar", "label": "OOC次數", "unit": "次"}},
    {{"key": "status", "type": "badge", "label": "診斷結論"}}
  ]
}}"""

        resp = await self._llm.create(
            system=system_prompt,
            messages=[{"role": "user", "content": f"Diagnostic rule (natural language):\n{description}"}],
            max_tokens=4096,
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.text.strip(), flags=re.MULTILINE).strip()
        if not raw:
            logger.warning("DR Phase 2 LLM returned empty response. Prompt length: %d chars", len(system_prompt))
            raise ValueError("LLM returned empty response — prompt may be too long or model refused")
        return json.loads(raw)
