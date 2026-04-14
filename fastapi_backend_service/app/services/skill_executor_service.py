"""SkillExecutorService v2.0 — Diagnostic-First execution sandbox.

Skill = pure diagnostic function.
  Injects: event_payload, execute_mcp (async)
  Captures: _findings variable assigned by LLM-generated code
  Returns:  SkillFindings { condition_met, evidence, impacted_lots }

trigger_alarm() removed. Alarm decisions delegated to Auto-Patrol.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.skill_definition import (
    SkillExecuteResponse,
    SkillFindings,
    SkillTryRunResponse,
    StepResult,
)
from app.services.mcp_definition_service import auto_resolve_process_context_params

logger = logging.getLogger(__name__)

# ── Security: forbidden patterns in Skill Python code ────────────────────────
_FORBIDDEN_PATTERNS = [
    r"\bimport\s+os\b",
    r"\bimport\s+sys\b",
    r"\bimport\s+subprocess\b",
    r"\b__import__\s*\(",
    r"\bopen\s*\(",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
]


def _security_check(code: str) -> Optional[str]:
    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            return f"Forbidden pattern in code: {pattern}"
    return None


def _validate_findings_against_schema(
    findings: SkillFindings,
    output_schema: List[Dict[str, Any]],
) -> List[str]:
    """Compare outputs/evidence keys against declared output_schema. Returns warnings."""
    if not output_schema:
        return []
    # Support both new format (key) and old format (field)
    declared = {f.get("key") or f.get("field") for f in output_schema if f.get("key") or f.get("field")}
    # Use outputs if present (new format), else evidence (legacy)
    actual = set(findings.outputs.keys()) if findings.outputs else set(findings.evidence.keys())
    missing = declared - actual
    extra = actual - declared
    warnings = []
    if missing:
        warnings.append(f"output_schema 宣告了但結果缺少: {sorted(missing)}")
    if extra:
        warnings.append(f"結果有但 output_schema 未宣告: {sorted(extra)}")
    return warnings


def build_mcp_executor(db, sim_url: str = "http://localhost:8012") -> Callable:
    """Factory: returns async (mcp_name, params) → Any callable backed by real DB + OntologySimulator."""
    mcp_repo = MCPDefinitionRepository(db)

    async def _executor(mcp_name: str, params: Dict[str, Any]) -> Any:
        mcp = await mcp_repo.get_by_name(mcp_name)
        if not mcp:
            logger.warning("execute_mcp: MCP '%s' not found in DB", mcp_name)
            return {}

        api_config = mcp.api_config if isinstance(mcp.api_config, dict) else {}
        try:
            if isinstance(mcp.api_config, str):
                api_config = json.loads(mcp.api_config)
        except Exception:
            pass

        endpoint_url: str = api_config.get("endpoint_url", "")
        if not endpoint_url:
            logger.warning("execute_mcp: MCP '%s' has no endpoint_url", mcp_name)
            return {}

        method = api_config.get("method", "GET").upper()

        # Normalize params (dedup for event MCPs, object_name→toolID mapping, etc.)
        from app.services.mcp_definition_service import (
            _normalize_params,
            _TIME_WINDOW_MCPS,
            _resolve_since_param,
            SinceParamError,
        )
        resolved: Dict[str, Any] = _normalize_params(dict(params), mcp_name=mcp_name)

        if mcp_name == "get_process_context":
            resolved = await auto_resolve_process_context_params(resolved, sim_url)
        if mcp_name in _TIME_WINDOW_MCPS:
            try:
                resolved = await _resolve_since_param(mcp_name, resolved, sim_url)
            except SinceParamError as exc:
                logger.warning("execute_mcp('%s'): %s", mcp_name, exc)
                return {
                    "status": "error",
                    "code": "INVALID_SINCE",
                    "message": str(exc),
                }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if method == "POST":
                    resp = await client.post(endpoint_url, json=resolved)
                else:
                    resp = await client.get(endpoint_url, params=resolved)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("execute_mcp('%s') HTTP call failed: %s", mcp_name, exc)
            return {}

    return _executor


class SkillExecutorService:
    def __init__(
        self,
        skill_repo: SkillDefinitionRepository,
        mcp_executor=None,   # callable: async (mcp_name, params) → Any
    ) -> None:
        self._skill_repo = skill_repo
        self._mcp_executor = mcp_executor
        self._mcp_call_counts: Dict[str, int] = {}  # tracks MCP call frequency per execution

    def _build_script(self, steps: List[Dict[str, Any]]) -> str:
        """Concatenate steps into a single async function with per-step output capture."""
        lines = ["async def _skill_main(event_payload, execute_mcp):"]
        lines.append("    import json as _json")
        lines.append("    _input       = event_payload")
        lines.append("    equipment_id = event_payload.get('equipment_id', '')")
        lines.append("    lot_id       = event_payload.get('lot_id', '')")
        lines.append("    step         = event_payload.get('step', '')")
        lines.append("    event_time   = event_payload.get('event_time', '')")
        lines.append("    _flat_data   = event_payload.get('_flat_data', {})")
        lines.append("    _step_outputs = {}")
        lines.append("")

        for s in steps:
            step_id = s.get("step_id", "step")
            nl = s.get("nl_segment", "")
            code = s.get("python_code", "")

            err = _security_check(code)
            if err:
                raise ValueError(f"[{step_id}] Security violation: {err}")

            lines.append(f"    # ── {step_id}: {nl}")
            lines.append(f"    _vars_before_{step_id} = set(dir())")
            for line in code.split("\n"):
                lines.append(f"    {line}")
            lines.append(f"    _new_vars_{step_id} = {{k: v for k, v in locals().items() if k not in _vars_before_{step_id} and not k.startswith('_')}}")
            lines.append(f"    try:")
            lines.append(f"        _step_outputs['{step_id}'] = _json.loads(_json.dumps(_new_vars_{step_id}, default=str))")
            lines.append(f"    except Exception:")
            lines.append(f"        _step_outputs['{step_id}'] = {{str(k): str(v) for k, v in _new_vars_{step_id}.items()}}")
            lines.append("")

        # Capture _findings assigned by LLM code
        lines.append("    _final_findings = None")
        lines.append("    try:")
        lines.append("        _final_findings = _findings")
        lines.append("    except NameError:")
        lines.append("        pass")
        # Capture _chart / _charts assigned by LLM code (visualization output)
        lines.append("    _final_charts = None")
        lines.append("    try:")
        lines.append("        _final_charts = _charts if isinstance(_charts, list) else [_charts]")
        lines.append("    except NameError:")
        lines.append("        pass")
        lines.append("    try:")
        lines.append("        if _final_charts is None and _chart is not None:")
        lines.append("            _final_charts = [_chart] if isinstance(_chart, dict) else None")
        lines.append("    except NameError:")
        lines.append("        pass")
        lines.append("    return {'step_outputs': _step_outputs, 'findings': _final_findings, 'charts': _final_charts}")
        return "\n".join(lines)

    def _build_findings(
        self,
        raw_findings: Optional[Dict[str, Any]],
        output_schema: List[Dict[str, Any]],
    ) -> SkillFindings:
        """Build SkillFindings from _findings variable + schema validation.

        Supports two formats:
          New: _findings = {condition_met, summary, outputs, impacted_lots}
          Old: _findings = {condition_met, evidence, impacted_lots}  (backward compat)
        """
        if not raw_findings or not isinstance(raw_findings, dict):
            return SkillFindings(
                condition_met=False,
                schema_warnings=["Skill code did not assign _findings variable"],
            )

        condition_met = bool(raw_findings.get("condition_met", False))
        impacted_lots = [str(l) for l in raw_findings.get("impacted_lots", []) if l]

        # New format: has 'outputs' key
        if "outputs" in raw_findings:
            findings = SkillFindings(
                condition_met=condition_met,
                summary=str(raw_findings.get("summary", "")),
                outputs=raw_findings.get("outputs", {}),
                impacted_lots=impacted_lots,
            )
        else:
            # Legacy format: has 'evidence' key — no summary/outputs
            findings = SkillFindings(
                condition_met=condition_met,
                evidence=raw_findings.get("evidence", {}),
                impacted_lots=impacted_lots,
            )

        findings.schema_warnings = _validate_findings_against_schema(findings, output_schema)
        return findings

    def get_mcp_call_counts(self) -> Dict[str, int]:
        """Return MCP call counts from the last execution (for self-test diagnostics)."""
        return dict(self._mcp_call_counts)

    async def _execute_mcp_wrapper(self, mcp_name: str, params: Dict[str, Any]) -> Any:
        self._mcp_call_counts[mcp_name] = self._mcp_call_counts.get(mcp_name, 0) + 1
        if self._mcp_executor:
            try:
                result = await self._mcp_executor(mcp_name, params)
                # Unwrap StandardResponse envelope (status: "ok" or "success")
                if isinstance(result, dict) and result.get("status") in ("ok", "success"):
                    data = result.get("data")
                    return data if data is not None else {}
                # Raw response (list or dict returned directly by OntologySimulator)
                return result
            except Exception as exc:
                logger.warning("execute_mcp('%s') failed: %s", mcp_name, exc)
                return {}
        return {}

    async def _run_script(
        self,
        steps: List[Dict[str, Any]],
        event_payload: Dict[str, Any],
    ) -> tuple[List[StepResult], Optional[Dict[str, Any]], Optional[str], Optional[List[Dict[str, Any]]]]:
        """Execute compiled script. Returns (step_results, raw_findings, error, charts)."""
        try:
            script = self._build_script(steps)
        except ValueError as exc:
            return [], None, str(exc), None

        step_results: List[StepResult] = []
        # Inject JS-style boolean/null aliases so LLM-generated code works even
        # when it mistakenly uses JavaScript literals (true/false/null).
        namespace: Dict[str, Any] = {"true": True, "false": False, "null": None}
        try:
            exec(script, namespace)  # defines _skill_main
            raw_result = await asyncio.wait_for(
                namespace["_skill_main"](event_payload, self._execute_mcp_wrapper),
                timeout=30.0,
            )
            raw_result = raw_result if isinstance(raw_result, dict) else {}
            step_outputs = raw_result.get("step_outputs", {})
            raw_findings = raw_result.get("findings")
            raw_charts = raw_result.get("charts")

            for s in steps:
                sid = s.get("step_id", "?")
                step_results.append(StepResult(
                    step_id=sid,
                    nl_segment=s.get("nl_segment", ""),
                    status="ok",
                    output=step_outputs.get(sid) if isinstance(step_outputs, dict) else None,
                ))
            return step_results, raw_findings, None, raw_charts

        except asyncio.TimeoutError:
            return step_results, None, "執行超時（30秒）", None
        except Exception as exc:
            return step_results, None, str(exc), None

    async def try_run(
        self,
        skill_id: int,
        mock_payload: Dict[str, Any],
    ) -> SkillTryRunResponse:
        """Sandbox try-run — does NOT write anything to DB."""
        t0 = time.monotonic()
        skill = await self._skill_repo.get_by_id(skill_id)
        if not skill:
            return SkillTryRunResponse(success=False, error=f"Skill id={skill_id} 不存在")

        steps = self._skill_repo.steps_mapping(skill)
        if not steps:
            return SkillTryRunResponse(success=False, error="此 Skill 尚無 steps_mapping")

        output_schema = self._skill_repo.get_output_schema(skill)
        step_results, raw_findings, error, _charts = await self._run_script(steps, mock_payload)
        elapsed_ms = (time.monotonic() - t0) * 1000

        if error:
            return SkillTryRunResponse(
                success=False, step_results=step_results,
                error=error, total_elapsed_ms=elapsed_ms,
            )

        findings = self._build_findings(raw_findings, output_schema)

        # ★ Chart Middleware — auto-generate charts from output_schema types
        # (same behaviour as execute() / try_run_draft() — was missing here, causing
        #  saved-rule try-run to return empty charts even when output_schema declared one)
        from app.services.chart_middleware import process as chart_process
        auto_charts = chart_process(findings.outputs, output_schema) if findings and output_schema else []
        all_charts = (_charts or []) + auto_charts

        return SkillTryRunResponse(
            success=True,
            step_results=step_results,
            findings=findings,
            charts=all_charts,
            total_elapsed_ms=elapsed_ms,
        )

    async def execute(
        self,
        skill_id: int,
        event_payload: Dict[str, Any],
        triggered_by: str = "manual",
    ) -> SkillExecuteResponse:
        """Real execution — returns findings for caller (Auto-Patrol) to act on."""
        skill = await self._skill_repo.get_by_id(skill_id)
        if not skill:
            return SkillExecuteResponse(success=False, error=f"Skill id={skill_id} 不存在")

        steps = self._skill_repo.steps_mapping(skill)
        if not steps:
            return SkillExecuteResponse(success=False, error="此 Skill 尚無 steps_mapping")

        output_schema = self._skill_repo.get_output_schema(skill)
        step_results, raw_findings, error, charts = await self._run_script(steps, event_payload)

        if error:
            return SkillExecuteResponse(success=False, step_results=step_results, error=error)

        findings = self._build_findings(raw_findings, output_schema)

        # Runtime output validation — log warnings if output doesn't match schema
        if findings and output_schema:
            schema_keys = {s["key"] for s in output_schema}
            output_keys = set(findings.outputs.keys()) if findings.outputs else set()
            missing = schema_keys - output_keys
            if missing:
                logger.warning(
                    "Skill id=%d output validation: missing keys %s (expected: %s, got: %s)",
                    skill_id, missing, schema_keys, output_keys,
                )

        # ★ Chart Middleware — auto-generate charts from output_schema types
        from app.services.chart_middleware import process as chart_process
        auto_charts = chart_process(findings.outputs, output_schema) if findings and output_schema else []
        all_charts = (charts or []) + auto_charts

        return SkillExecuteResponse(
            success=True,
            step_results=step_results,
            findings=findings,
            charts=all_charts,
        )

    async def try_run_draft(
        self,
        steps: List[Dict[str, Any]],
        mock_payload: Dict[str, Any],
        output_schema: Optional[List[Dict[str, Any]]] = None,
    ) -> SkillTryRunResponse:
        """Sandbox try-run without a saved skill — v3.0 draft flow."""
        t0 = time.monotonic()
        if not steps:
            return SkillTryRunResponse(success=False, error="steps_mapping 不能為空")

        step_results, raw_findings, error, _charts = await self._run_script(steps, mock_payload)
        elapsed_ms = (time.monotonic() - t0) * 1000

        if error:
            return SkillTryRunResponse(
                success=False, step_results=step_results,
                error=error, total_elapsed_ms=elapsed_ms,
            )

        findings = self._build_findings(raw_findings, output_schema or [])

        # ★ Chart Middleware
        from app.services.chart_middleware import process as chart_process
        auto_charts = chart_process(findings.outputs, output_schema or []) if findings else []
        all_charts = (_charts or []) + auto_charts

        return SkillTryRunResponse(
            success=True,
            step_results=step_results,
            findings=findings,
            charts=all_charts,
            total_elapsed_ms=elapsed_ms,
        )
