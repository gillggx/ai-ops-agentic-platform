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

# _FALLBACK_SAMPLES removed — MCP catalog is now dynamic from DB.
# Sample responses come from real MCP calls during Phase 1.5.

async def _build_mcp_catalog_from_db(db) -> str:
    """Dynamically build MCP catalog from DB system MCPs for LLM prompt injection."""
    from app.repositories.mcp_definition_repository import MCPDefinitionRepository
    repo = MCPDefinitionRepository(db)
    mcps = await repo.get_all_by_type("system")

    lines = ["Available MCPs (use ONLY these):\n"]
    for mcp in mcps:
        name = mcp.name
        desc = (mcp.description or "").split("\n")[0][:120]  # first line, truncated

        # Parse input_schema fields
        schema_raw = mcp.input_schema
        if isinstance(schema_raw, str):
            import json as _j
            try:
                schema_raw = _j.loads(schema_raw)
            except Exception:
                schema_raw = {}
        fields = schema_raw.get("fields", []) if isinstance(schema_raw, dict) else []

        params_parts = []
        for f in fields:
            fname = f.get("name", "?")
            ftype = f.get("type", "string")
            freq = "required" if f.get("required") else "optional"
            fdesc = f.get("description", "")[:60]
            params_parts.append(f"    {fname} ({ftype}, {freq}): {fdesc}")

        params_str = "\n".join(params_parts) if params_parts else "    (no parameters)"

        lines.append(f"- {name}")
        lines.append(f"  {desc}")
        lines.append(f"  params:")
        lines.append(params_str)
        lines.append("")

    lines.append("⚠️ CRITICAL — MCP RESPONSE FORMAT RULES:")
    lines.append("  1. get_process_events returns a LIST (not dict). Use: events = result if isinstance(result, list) else []")
    lines.append("  2. get_process_info returns a LIST of {event: {...}, objects: {...}}. Same pattern.")
    lines.append("  3. ALL field names are camelCase:")
    lines.append("     event.get('eventTime')  ← NOT 'timestamp'")
    lines.append("     event.get('lotID')      ← NOT 'lot_id'")
    lines.append("     event.get('toolID')     ← NOT 'tool_id'")
    lines.append("     event.get('spc_status') ← 'PASS' or 'OOC' (NOT 'status', NOT 'FAIL')")
    lines.append("  4. get_process_events does NOT return measurement values. Use get_process_info for DC/SPC/APC data.")
    lines.append("")

    return "\n".join(lines)

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


def _extract_json(text: str) -> dict:
    """Robustly extract and parse the first JSON object from LLM output.

    Pipeline: strip think tags → strip markdown → isolate {...} → repair → parse.
    Returns parsed dict (raises on total failure).
    """
    # 1. Strip <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # 2. Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # 3. Isolate outermost {...}
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in LLM output (length={len(text)})")
    depth = 0
    end = len(text)
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    raw = text[start:end]
    # 4. Try parse as-is first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 5. Repair common LLM JSON issues and retry
    repaired = _repair_json(raw)
    return json.loads(repaired)


def _repair_json(text: str) -> str:
    """Fix common JSON issues produced by LLMs.

    Handles: trailing commas, JS comments, single quotes, unescaped newlines in strings.
    """
    # Remove single-line comments  // ...
    text = re.sub(r'//[^\n]*', '', text)
    # Remove multi-line comments  /* ... */
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Replace unescaped newlines inside strings (heuristic: between two ")
    # Process character by character to find strings and fix them
    result = []
    in_str = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            result.append(ch)
            continue
        if in_str and ch == '\n':
            result.append('\\n')
            continue
        result.append(ch)
    return ''.join(result)


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


def _sanitize_code(code: str) -> str:
    """Insert 'pass' into any empty block body (else/except/finally/for/while/with/if).

    LLMs occasionally generate `else:` or `except:` with no following body,
    which raises SyntaxError. This post-processor detects those and adds `pass`.
    """
    lines = code.splitlines()
    result = []
    block_keywords = re.compile(r"^(\s*)(else|elif\b.*|except\b.*|finally|for\b.*|while\b.*|with\b.*|if\b.*):\s*$")
    for i, line in enumerate(lines):
        result.append(line)
        if block_keywords.match(line):
            # Check if next non-empty line is at deeper indentation
            current_indent = len(line) - len(line.lstrip())
            next_code_line = None
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    next_code_line = lines[j]
                    break
            if next_code_line is None or (len(next_code_line) - len(next_code_line.lstrip())) <= current_indent:
                result.append(" " * (current_indent + 4) + "pass")
    return "\n".join(result)


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


def _build_confirmed_section(mcp_calls: List[dict], sample_responses: Dict[str, Any]) -> str:
    """Build the 'Confirmed MCPs' context block shared by Phase 2a and 2b prompts."""
    lines = ["Confirmed MCPs to use (execute in this order):"]
    for i, mc in enumerate(mcp_calls, 1):
        mcp_name = mc["mcp_name"]
        purpose = mc.get("purpose", "")
        tmpl = mc.get("params_template", {})

        sample = sample_responses.get(mcp_name)
        sample_str = ""
        if sample:
            preview = sample[:2] if isinstance(sample, list) else sample
            sample_str = f"\n   Sample response: {json.dumps(preview, ensure_ascii=False)[:500]}"

        lines.append(
            f"{i}. execute_mcp('{mcp_name}', {json.dumps(tmpl, ensure_ascii=False)})\n"
            f"   Purpose: {purpose}{sample_str}"
        )

    lines.append("")
    lines.append("⚠️ REMEMBER: OOC detection uses 'spc_status' field, NOT 'status'.")
    return "\n".join(lines)


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

    # ── Fix Skill (error auto-fix or user feedback) ────────────────────────

    async def fix_skill(
        self,
        rule_id: int,
        error_message: str = "",
        user_feedback: str = "",
    ) -> dict:
        """Regenerate all steps for a skill using error context + optional user feedback.

        Returns {"success": bool, "steps_mapping": [...], "error": str|None}.
        """
        obj = await self._repo.get_by_id(rule_id)
        if not obj:
            return {"success": False, "error": f"Skill id={rule_id} 不存在"}

        description = obj.auto_check_description or obj.description or obj.name
        raw_steps = obj.steps_mapping
        if isinstance(raw_steps, str):
            raw_steps = json.loads(raw_steps)
        # Handle double-encoded JSON string
        if isinstance(raw_steps, str):
            raw_steps = json.loads(raw_steps)
        steps = raw_steps if isinstance(raw_steps, list) else []

        raw_in = obj.input_schema
        if isinstance(raw_in, str):
            raw_in = json.loads(raw_in)
        input_schema = raw_in if isinstance(raw_in, list) else []

        raw_out = obj.output_schema
        if isinstance(raw_out, str):
            raw_out = json.loads(raw_out)
        output_schema = raw_out if isinstance(raw_out, list) else []

        # Build current code context
        current_code = ""
        for s in steps:
            if isinstance(s, dict):
                current_code += f"\n# --- {s.get('step_id','?')}: {s.get('nl_segment','')} ---\n{s.get('python_code','')}\n"

        mcp_catalog = await _build_mcp_catalog_from_db(self._db)

        fix_prompt = f"""\
You are a factory AI expert. Fix the Python code for a diagnostic skill.
The skill was executed but FAILED. Regenerate ALL steps with corrected code.
Output raw Python code ONLY for each step — no JSON wrapper, no markdown.

Rule description: {description}

{mcp_catalog}

Current code that FAILED:
{current_code}

Error message:
{error_message}

{"User feedback: " + user_feedback if user_feedback else ""}

INPUT VARIABLES (available as top-level Python vars):
  equipment_id: str, lot_id: str, step: str, event_time: str, _input: dict

Special function: await execute_mcp(mcp_name: str, params: dict) -> Any
Forbidden: import, open(), exec(), eval(), os, sys, subprocess

Fix the code and output each step separated by "# === STEP_BREAK ===" marker.
Step {len(steps)} is the LAST step and MUST end with _findings = {{"condition_met": <bool>, "summary": "<Chinese>", "outputs": {{...}}, "impacted_lots": [...]}}
"""

        try:
            resp = await self._llm.create(
                system=fix_prompt,
                messages=[{"role": "user", "content": "請修正以上的程式碼。"}],
                max_tokens=4096,
            )

            raw_code = resp.text.strip()
            raw_code = re.sub(r"```(?:python)?\s*|\s*```", "", raw_code, flags=re.MULTILINE).strip()
            raw_code = re.sub(r"<think>.*?</think>", "", raw_code, flags=re.DOTALL).strip()

            # Split by marker
            parts = re.split(r"#\s*===\s*STEP_BREAK\s*===", raw_code)
            parts = [p.strip() for p in parts if p.strip()]

            if len(parts) != len(steps):
                # Fallback: try to split evenly or use as single block
                if len(parts) == 1 and len(steps) > 1:
                    # LLM didn't use markers — put everything in steps
                    # Best effort: assign all to the steps sequentially
                    parts = [parts[0]]  # will be handled below

            # Rebuild steps_mapping
            new_steps = []
            for i, s in enumerate(steps):
                code = parts[i] if i < len(parts) else parts[-1] if parts else ""
                new_steps.append({
                    "step_id": s["step_id"],
                    "nl_segment": s["nl_segment"],
                    "python_code": code,
                })

            # Save to DB
            steps_json = json.dumps(new_steps, ensure_ascii=False)
            await self._repo.update(rule_id, {"steps_mapping": steps_json})

            return {
                "success": True,
                "steps_mapping": new_steps,
                "steps_count": len(new_steps),
            }
        except Exception as exc:
            logger.exception("fix_skill failed: %s", exc)
            return {"success": False, "error": str(exc)}

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

        # ── Phase 2a: Step Planner ────────────────────────────────────────────
        yield _sse({"type": "phase", "phase": "2a", "message": "規劃分析步驟..."})

        try:
            step_plan = await self._plan_steps(body.auto_check_description, mcp_calls, sample_responses)
        except Exception as exc:
            logger.warning("DR Phase 2a failed: %s", exc)
            yield _sse({"type": "error", "error": f"Phase 2a 失敗: {exc}"})
            return

        raw_steps: List[dict] = step_plan.get("steps", [])
        input_schema: List[dict] = step_plan.get("input_schema", [])
        output_schema: List[dict] = step_plan.get("output_schema", [])
        proposal_steps: List[str] = step_plan.get(
            "proposal_steps", [s.get("nl_segment", "") for s in raw_steps]
        )

        if not raw_steps:
            yield _sse({"type": "error", "error": "Phase 2a 未能規劃出分析步驟，請修改描述後重試"})
            return

        yield _sse({
            "type": "step_plan",
            "steps": raw_steps,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "total": len(raw_steps),
        })
        for s in raw_steps:
            yield _sse({"type": "log", "message": f"  → {s['step_id']}: {s['nl_segment']}"})

        # ── Phase 2b: Per-Step Code Generation ───────────────────────────────
        yield _sse({"type": "phase", "phase": "2b", "message": f"生成每步程式碼 (共 {len(raw_steps)} 步)..."})

        confirmed_section = _build_confirmed_section(mcp_calls, sample_responses)
        assembled_steps: List[dict] = []
        generated_code: List[str] = []

        for i, raw_step in enumerate(raw_steps):
            step_id = raw_step["step_id"]
            nl_segment = raw_step.get("nl_segment", "")
            yield _sse({"type": "step_code", "status": "generating", "step_id": step_id, "nl_segment": nl_segment})
            try:
                python_code = await self._generate_step_code(
                    body.auto_check_description,
                    confirmed_section,
                    raw_steps,
                    i,
                    output_schema,
                    generated_code,
                )
                assembled_steps.append({
                    "step_id": step_id,
                    "nl_segment": nl_segment,
                    "python_code": python_code,
                })
                generated_code.append(python_code)
                yield _sse({"type": "step_code", "status": "done", "step_id": step_id})
            except Exception as exc:
                logger.warning("DR Phase 2b step '%s' failed: %s", step_id, exc)
                yield _sse({"type": "step_code", "status": "error", "step_id": step_id, "error": str(exc)})
                yield _sse({"type": "error", "error": f"Phase 2b 步驟 {step_id} 失敗: {exc}"})
                return

        # ── Phase 3: Self-Test — auto try-run and validate ────────────────
        yield _sse({"type": "self_test", "status": "running"})

        try:
            from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor
            from app.config import get_settings as _get_settings
            test_executor = SkillExecutorService(
                skill_repo=self._repo,
                mcp_executor=build_mcp_executor(self._db, sim_url=_get_settings().ONTOLOGY_SIM_URL),
            )
            test_payload = {"equipment_id": "EQP-01", "lot_id": "", "step": "", "event_time": ""}
            test_result = await test_executor.try_run_draft(
                steps=assembled_steps,
                mock_payload=test_payload,
                output_schema=output_schema,
            )

            if test_result.success:
                # Validate output structure
                findings = test_result.findings
                validation_issues = []
                if findings:
                    if not hasattr(findings, "condition_met") and not isinstance(findings, dict):
                        validation_issues.append("missing condition_met")
                    outputs = findings.outputs if hasattr(findings, "outputs") else (findings.get("outputs") if isinstance(findings, dict) else {})
                    if not outputs:
                        validation_issues.append("outputs is empty")
                    else:
                        schema_keys = {s["key"] for s in output_schema}
                        output_keys = set(outputs.keys()) if isinstance(outputs, dict) else set()
                        missing = schema_keys - output_keys
                        if missing:
                            validation_issues.append(f"missing output keys: {missing}")

                if validation_issues:
                    yield _sse({"type": "self_test", "status": "warning", "issues": validation_issues})
                else:
                    yield _sse({"type": "self_test", "status": "pass"})
            else:
                # Try-run failed — attempt auto-fix
                error_msg = test_result.error or "Unknown error"
                yield _sse({"type": "self_test", "status": "fail", "error": error_msg})
                yield _sse({"type": "self_test", "status": "fixing"})

                fix_result = await self._fix_steps_with_error(
                    description=body.auto_check_description,
                    steps=assembled_steps,
                    error_message=error_msg,
                    output_schema=output_schema,
                    confirmed_section=confirmed_section,
                )
                if fix_result:
                    assembled_steps = fix_result
                    yield _sse({"type": "self_test", "status": "fixed", "steps_count": len(assembled_steps)})
                else:
                    yield _sse({"type": "self_test", "status": "fix_failed"})

        except Exception as exc:
            logger.warning("Self-test failed (non-blocking): %s", exc)
            yield _sse({"type": "self_test", "status": "error", "error": str(exc)})

        yield _sse({
            "type": "done",
            "result": {
                "proposal_steps": proposal_steps,
                "steps_mapping": assembled_steps,
                "input_schema": input_schema,
                "output_schema": output_schema,
            },
        })

    async def _fix_steps_with_error(
        self,
        description: str,
        steps: List[dict],
        error_message: str,
        output_schema: List[dict],
        confirmed_section: str,
    ) -> Optional[List[dict]]:
        """Try to fix generated steps using error context. Returns fixed steps or None."""
        current_code = "\n".join(
            f"# --- {s['step_id']}: {s['nl_segment']} ---\n{s['python_code']}"
            for s in steps
        )

        out_keys = ", ".join(f'"{s["key"]}": <value>' for s in output_schema)

        fix_prompt = f"""\
You are a factory AI expert. The generated Python code FAILED during self-test.
Fix ALL steps and output corrected Python code.
Output raw Python code for each step, separated by "# === STEP_BREAK ===" marker.

Rule description: {description}

{confirmed_section}

Current BROKEN code:
{current_code}

ERROR:
{error_message}

RULES:
- execute_mcp returns a LIST (not dict) for get_process_events
- Field names are camelCase: lotID, toolID, eventTime, spc_status (NOT lot_id, tool_id, timestamp)
- spc_status values: 'PASS' or 'OOC' only (NOT 'FAIL')
- Last step MUST end with _findings = {{"condition_met": <bool>, "summary": "...", "outputs": {{{out_keys}}}, "impacted_lots": [...]}}

Fix the code now. Output {len(steps)} code blocks separated by # === STEP_BREAK ===
"""

        try:
            resp = await self._llm.create(
                system=fix_prompt,
                messages=[{"role": "user", "content": "修正程式碼。"}],
                max_tokens=4096,
            )
            raw = resp.text.strip()
            raw = re.sub(r"```(?:python)?\s*|\s*```", "", raw, flags=re.MULTILINE).strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

            parts = re.split(r"#\s*===\s*STEP_BREAK\s*===", raw)
            parts = [p.strip() for p in parts if p.strip()]

            if not parts:
                return None

            fixed = []
            for i, s in enumerate(steps):
                code = parts[i] if i < len(parts) else parts[-1]
                fixed.append({
                    "step_id": s["step_id"],
                    "nl_segment": s["nl_segment"],
                    "python_code": code,
                    "expected_result": s.get("expected_result", ""),
                })
            return fixed
        except Exception as exc:
            logger.warning("_fix_steps_with_error failed: %s", exc)
            return None

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
        mcp_catalog = await _build_mcp_catalog_from_db(self._db)
        system_prompt = f"""\
You are a factory AI data planning expert.
Given a diagnostic rule description, decide which MCPs are needed and in what order.
Output ONLY valid JSON. No explanation, no markdown fences.

{mcp_catalog}

Runtime variables available (use in params_template):
  equipment_id: target equipment ID (e.g. "EQP-01") — always available for event-driven rules
  lot_id: lot ID — may be empty
  step: step code — may be empty
  event_time: ISO8601 timestamp — may be empty

Rules:
- Only use MCPs from the catalog above
- Max 5 MCP calls
- params_template: use {{{{variable_name}}}} for dynamic values (e.g. {{{{equipment_id}}}})
- List in execution order

Required output format:
{{
  "reasoning": "brief explanation of what data is needed and why",
  "mcp_calls": [
    {{"mcp_name": "get_process_events", "purpose": "取機台最近製程事件清單", "params_template": {{"toolID": "{{{{equipment_id}}}}", "since": "7d"}}}},
    {{"mcp_name": "get_process_info", "purpose": "取某批次某站的完整製程資料(含DC/SPC/APC/RECIPE)", "params_template": {{"lotID": "{{{{lot_id}}}}", "step": "{{{{step}}}}"}}}}
  ]
}}"""

        resp = await self._llm.create(
            system=system_prompt,
            messages=[{"role": "user", "content": f"Diagnostic rule description:\n{description}"}],
            max_tokens=2048,
        )
        return _extract_json(resp.text)

    # ── Private: Phase 2a — Step Planner ──────────────────────────────────────

    async def _plan_steps(
        self,
        description: str,
        mcp_calls: List[dict],
        sample_responses: Dict[str, Any],
    ) -> dict:
        """Phase 2a: plan step structure only — no python_code. Very short response."""
        confirmed_section = _build_confirmed_section(mcp_calls, sample_responses)

        system_prompt = f"""\
You are a factory AI monitoring expert. Plan the diagnostic analysis steps.
Output ONLY valid JSON. No explanation, no markdown fences.

{confirmed_section}

INPUT vars available in Python scope: equipment_id, lot_id, step, event_time, _input

CRITICAL RULES:
- Maximum 3-5 steps. NEVER more than 5.
- Use FOR LOOPS inside a step for repetitive work (e.g. "iterate each process record to fetch APC context").
- Do NOT create one step per record — that defeats the purpose of loops.
- Good: "step2: loop through each process record and fetch APC parameters"
- Bad: "step2: fetch APC for lot 1", "step3: fetch APC for lot 2", ...

{_OUTPUT_SCHEMA_GUIDE}

Required output format (NO python_code — plan only):
{{
  "proposal_steps": ["Plain English step 1", "Plain English step 2", ...],
  "steps": [
    {{"step_id": "step1", "nl_segment": "取機台最近 N 次製程清單", "expected_result": "list of dicts with keys: eventTime, lotID, toolID, step, spc_status. At least 1 record."}},
    {{"step_id": "step2", "nl_segment": "用 for loop 逐筆取各批次 APC 參數", "expected_result": "list of dicts with APC parameter values. Same length as step1 OOC records."}},
    {{"step_id": "step3", "nl_segment": "計算偏移趨勢並判斷 OOC 條件，輸出診斷結果", "expected_result": "_findings dict with condition_met, summary, outputs, impacted_lots"}}
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
            messages=[{"role": "user", "content": f"Diagnostic rule:\n{description}"}],
            max_tokens=2048,
        )
        return _extract_json(resp.text)

    # ── Private: Phase 2b — Per-Step Code Generator ────────────────────────────

    async def _generate_step_code(
        self,
        description: str,
        confirmed_section: str,
        all_steps: List[dict],
        step_index: int,
        output_schema: List[dict],
        previous_code: List[str],
    ) -> str:
        """Phase 2b: generate raw python_code for one step. Output is code only, not JSON."""
        step = all_steps[step_index]
        is_last = step_index == len(all_steps) - 1

        steps_overview = "\n".join(
            f"  {i + 1}. [{s['step_id']}] {s['nl_segment']}"
            for i, s in enumerate(all_steps)
        )

        # Show previous steps' actual code so variable names are consistent
        prev_code_section = ""
        if previous_code:
            prev_parts = []
            for i, code in enumerate(previous_code):
                prev_parts.append(f"# --- {all_steps[i]['step_id']} ---\n{code}")
            prev_code_section = (
                "\nCode from previous steps (use the SAME variable names):\n"
                + "\n\n".join(prev_parts)
                + "\n"
            )

        last_step_note = ""
        if is_last:
            out_keys = ", ".join(f'"{s["key"]}": <value>' for s in output_schema)
            # Build chart format hints from output_schema
            chart_hints = []
            for s in output_schema:
                if s.get("type") in ("line_chart", "bar_chart", "scatter_chart"):
                    xk = s.get("x_key", "index")
                    yks = s.get("y_keys", ["value"])
                    chart_hints.append(
                        f'  "{s["key"]}": must be a LIST of dicts, e.g. '
                        f'[{{"{xk}": 0, "{yks[0]}": 1.23}}, {{"{xk}": 1, "{yks[0]}": 1.45}}, ...]'
                    )
            chart_note = ""
            if chart_hints:
                chart_note = "\nCHART DATA FORMAT — outputs for chart-type keys MUST be a list of dicts:\n" + "\n".join(chart_hints)

            last_step_note = f"""
CRITICAL — this is the LAST step. End with exactly:
_findings = {{
    "condition_met": <bool>,
    "summary": "<one sentence conclusion in Chinese>",
    "outputs": {{{out_keys}}},
    "impacted_lots": [<lot_id_str>] if condition_met else []
}}{chart_note}"""

        system_prompt = f"""\
You are a factory AI expert. Write Python code for ONE diagnostic step.
Output raw Python code ONLY — no JSON, no markdown fences, no explanation.

Rule description: {description}

{confirmed_section}

Special function (awaitable, no import needed):
  await execute_mcp(mcp_name: str, params: dict) -> Any

Forbidden: import, open(), exec(), eval(), os, sys, subprocess, trigger_alarm

INPUT VARIABLES (available as top-level Python vars):
  equipment_id: str  — target equipment ID (e.g. "EQP-01") from event_payload or user input
  lot_id: str        — lot ID (e.g. "LOT-0001") — may be empty
  step: str          — step code (e.g. "STEP_045") — may be empty
  event_time: str    — ISO8601 timestamp — may be empty
  _input: dict       — raw input dict (same data as above)

SCOPE: All steps share the SAME Python scope. Variables from step 1 are available in step 2.
  Do NOT use _next_input or _input to pass data between steps. Just use regular variables.
SCOPE: All steps share the SAME Python scope. Variables from step 1 are directly available in step 2.
  Do NOT use _next_input or _input to pass data between steps.
  _input is ONLY for the original user input, NOT for inter-step data.
  Just use regular variables — e.g. step 1 sets `process_list = [...]`, step 2 reads `process_list` directly.
CRITICAL: Every if/else/for/while/try/except block MUST have a body — never leave a block header with no statements.
{prev_code_section}
All steps overview:
{steps_overview}
{last_step_note}"""

        resp = await self._llm.create(
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"Write Python code for step {step_index + 1}/{len(all_steps)}: "
                    f"[{step['step_id']}] {step['nl_segment']}"
                ),
            }],
            max_tokens=3072 if is_last else 2048,
        )
        code = re.sub(r"<think>.*?</think>", "", resp.text, flags=re.DOTALL)
        code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code.strip(), flags=re.MULTILINE).strip()
        if not code:
            raise ValueError(f"LLM returned empty code for step {step['step_id']}")
        return _sanitize_code(code)
