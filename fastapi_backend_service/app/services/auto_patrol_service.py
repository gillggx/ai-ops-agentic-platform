"""AutoPatrolService v2.0 — orchestrates Skill execution + alarm decisions.

Execution flow:
  patrol triggered (event or schedule)
  → SkillExecutorService.execute(skill_id, event_payload)
  → findings.condition_met?
      True  → create Alarm(severity, title, evidence) via AlarmRepository
      False → no action
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.alarm_repository import AlarmRepository
from app.repositories.auto_patrol_repository import AutoPatrolRepository
from app.repositories.execution_log_repository import ExecutionLogRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.auto_patrol import (
    AutoPatrolCreate,
    AutoPatrolTriggerResponse,
    AutoPatrolUpdate,
)
from app.services.context_builder_service import (
    build_event_context,
    build_schedule_context,
    expand_to_targets,
)
from app.services.skill_executor_service import SkillExecutorService

logger = logging.getLogger(__name__)


# ── P1 Phase ε: run a Diagnostic Rule via Pipeline Builder ────────────────

async def run_dr_via_pipeline(
    db,
    dr_skill,
    alarm_id: int,
    alarm_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a DR's bound pipeline and return a findings dict compatible
    with the legacy Skill executor's result shape.

    Returns {"success": bool, "findings": dict|None, "error": str|None}.

    Findings dict shape (matches SkillFindings.model_dump()):
      - condition_met: bool
      - summary: str
      - outputs: dict (per skill.output_schema)
    """
    import json as _json
    import time as _time
    from app.repositories.pipeline_repository import PipelineRepository, PipelineRunRepository
    from app.services.pipeline_builder.block_registry import BlockRegistry
    from app.services.pipeline_builder.executor import PipelineExecutor
    from app.schemas.pipeline import PipelineJSON

    pipeline_id = dr_skill.pipeline_id
    if pipeline_id is None:
        return {"success": False, "findings": None, "error": "DR has no pipeline_id"}

    pipeline_repo = PipelineRepository(db)
    pipeline_row = await pipeline_repo.get_by_id(pipeline_id)
    if pipeline_row is None:
        return {"success": False, "findings": None,
                "error": f"pipeline {pipeline_id} not found"}
    try:
        pipeline_json = PipelineJSON.model_validate(_json.loads(pipeline_row.pipeline_json))
    except Exception as e:
        return {"success": False, "findings": None,
                "error": f"invalid pipeline JSON: {e}"}

    # Build input resolution — DR pipelines expect `tool_id`, usually sourced
    # from the alarm's equipment_id. Fall back to other common keys for safety.
    tool_id = (alarm_context.get("equipment_id")
               or alarm_context.get("tool_id")
               or alarm_context.get("toolID") or "")
    resolved_inputs = {"tool_id": tool_id}

    registry = BlockRegistry()
    await registry.load_from_db(db)
    executor = PipelineExecutor(registry)
    run_repo = PipelineRunRepository(db)
    run = await run_repo.create_run(
        pipeline_id=pipeline_id,
        pipeline_version=pipeline_row.version or "1.0.0",
        triggered_by=f"alarm:{alarm_id}",
        status="running",
    )
    await db.commit()

    t0 = _time.monotonic()
    try:
        result = await executor.execute(pipeline_json, run_id=run.id, inputs=resolved_inputs)
    except Exception as exc:
        logger.exception("DR pipeline execution crashed for pipeline=%d: %s", pipeline_id, exc)
        err = f"{type(exc).__name__}: {exc}"
        await run_repo.finish_run(run_id=run.id, status="failed",
                                  node_results={}, error_message=err)
        await db.commit()
        return {"success": False, "findings": None, "error": err}

    await run_repo.finish_run(run_id=run.id, status=result["status"],
                              node_results=result["node_results"],
                              error_message=result.get("error_message"))
    await db.commit()
    logger.info(
        "DR pipeline run: pipeline=%d alarm=%d status=%s duration_ms=%d",
        pipeline_id, alarm_id, result["status"],
        int((_time.monotonic() - t0) * 1000),
    )

    # Convert pipeline result → SkillFindings-compatible dict.
    summary = result.get("result_summary") or {}
    condition_met = bool(summary.get("triggered", False))

    # Aggregate each node's preview rows into outputs keyed by node id.
    outputs: Dict[str, Any] = {}
    for node_id, node_res in (result.get("node_results") or {}).items():
        preview = (node_res or {}).get("preview") or {}
        for port_name, port_data in preview.items():
            if port_data and isinstance(port_data, dict) and "rows" in port_data:
                key = f"{node_id}_{port_name}" if port_name != "data" else node_id
                outputs[key] = port_data.get("rows")

    summary_text = summary.get("summary") or (
        f"Pipeline {pipeline_id} triggered" if condition_met else
        f"Pipeline {pipeline_id} did not meet condition"
    )
    findings = {
        "condition_met": condition_met,
        "summary": summary_text,
        "outputs": outputs,
    }
    return {"success": result["status"] == "success", "findings": findings, "error": None}


# ── Phase 4-B: pipeline input-binding resolver ──────────────────────────────

def _resolve_input_binding(
    binding: Optional[Dict[str, Any]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve input_binding values into a concrete dict for the executor.

    Supported ref syntax in binding values:
      - Literal (any non-string, or string not starting with '$')
      - `$event.<key>` or `$context.<key>` — pulled from `context` dict
      - `$ENV.<name>` — read from os.environ (rarely needed; here for parity)

    Context-flattening: `context` is treated as a flat dict; `$event.x` and
    `$context.x` both read `context[x]` (we don't currently split event vs
    context scopes at the service level — caller merges upstream).

    P1 Phase ε: when `binding` is empty/None, auto-derive `tool_id` from the
    common event payload shapes (`equipment_id`, `toolID`, `tool_id`). This
    is the Phase 7c silent-failure root cause — patrols with NULL input_binding
    were passing empty inputs to the pipeline, which rejected them as
    MISSING_INPUT and returned no alarm.
    """
    import os
    resolved: Dict[str, Any] = {}
    if not binding:
        tool_id = (context.get("tool_id")
                   or context.get("equipment_id")
                   or context.get("toolID"))
        if tool_id:
            resolved["tool_id"] = tool_id
        # Surface other commonly-referenced event fields for pipelines that
        # may declare optional inputs (lot_id, step, event_time).
        for key in ("lot_id", "step", "event_time"):
            val = context.get(key)
            if val is not None:
                resolved[key] = val
        return resolved
    for k, v in binding.items():
        if isinstance(v, str) and v.startswith("$"):
            if v.startswith("$event.") or v.startswith("$context."):
                ref_key = v.split(".", 1)[1]
                resolved[k] = context.get(ref_key)
            elif v.startswith("$ENV."):
                resolved[k] = os.environ.get(v.split(".", 1)[1])
            else:
                # Unknown $ prefix — leave as literal to let executor complain
                resolved[k] = v
        else:
            resolved[k] = v
    # Even when binding is provided, backfill tool_id if missing from binding
    # but present in context. Common case: binding specifies lot_id only.
    if "tool_id" not in resolved:
        tool_id = (context.get("tool_id")
                   or context.get("equipment_id")
                   or context.get("toolID"))
        if tool_id:
            resolved["tool_id"] = tool_id
    return resolved


class AutoPatrolService:
    def __init__(
        self,
        repo: AutoPatrolRepository,
        alarm_repo: AlarmRepository,
        executor: SkillExecutorService,
        sim_url: str = "http://localhost:8012",
    ) -> None:
        self._repo = repo
        self._alarm_repo = alarm_repo
        self._executor = executor
        self._sim_url = sim_url

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def list_all(self, active_only: bool = False) -> List[Dict[str, Any]]:
        items = await self._repo.list_all(active_only=active_only)
        return [self._repo.to_response_dict(i) for i in items]

    async def get(self, patrol_id: int) -> Dict[str, Any]:
        obj = await self._repo.get_by_id(patrol_id)
        if not obj:
            raise ValueError(f"Auto-Patrol id={patrol_id} 不存在")
        result = self._repo.to_response_dict(obj)

        # Include embedded skill's steps_mapping, input_schema, output_schema
        if obj.skill_id:
            import json as _json
            skill_repo = SkillDefinitionRepository(self._repo._db)
            skill = await skill_repo.get_by_id(obj.skill_id)
            if skill:
                try:
                    result["steps_mapping"] = _json.loads(skill.steps_mapping) if isinstance(skill.steps_mapping, str) else (skill.steps_mapping or [])
                except Exception:
                    result["steps_mapping"] = []
                try:
                    result["input_schema"] = _json.loads(skill.input_schema) if isinstance(skill.input_schema, str) else (skill.input_schema or [])
                except Exception:
                    result["input_schema"] = []
                try:
                    result["output_schema"] = _json.loads(skill.output_schema) if isinstance(skill.output_schema, str) else (skill.output_schema or [])
                except Exception:
                    result["output_schema"] = []

        return result

    async def create(self, body: AutoPatrolCreate, created_by: Optional[int] = None) -> Dict[str, Any]:
        from app.repositories.pipeline_repository import PipelineRepository

        data = body.model_dump()
        steps = data.pop("steps_mapping", [])
        input_schema = data.pop("input_schema", [])
        output_schema = data.pop("output_schema", [])

        # Phase 4-B: if pipeline_id provided, skip embedded-skill creation.
        if data.get("pipeline_id") is not None:
            # PR-B gate: only allow binding to active + auto_patrol pipelines.
            pipeline_repo = PipelineRepository(self._repo._db)
            bound = await pipeline_repo.get_by_id(data["pipeline_id"])
            if bound is None:
                raise ValueError(f"Pipeline {data['pipeline_id']} not found")
            if bound.status != "active":
                raise ValueError(
                    f"Auto-Patrol must bind to an ACTIVE pipeline (got '{bound.status}') — "
                    "publish the pipeline first"
                )
            if getattr(bound, "pipeline_kind", "diagnostic") != "auto_patrol":
                raise ValueError(
                    f"Pipeline {data['pipeline_id']} is kind='{getattr(bound, 'pipeline_kind', '?')}' — "
                    "only kind='auto_patrol' pipelines can back an Auto-Patrol"
                )
            data["skill_id"] = None
        else:
            # Auto-create the embedded skill (legacy source="auto_patrol")
            skill_repo = SkillDefinitionRepository(self._repo._db)
            skill = await skill_repo.create({
                "name": f"[auto_patrol] {body.name}",
                "description": body.auto_check_description or body.description,
                "auto_check_description": body.auto_check_description or "",
                "source": "auto_patrol",
                "trigger_mode": "event",
                "steps_mapping": steps,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "visibility": "private",
                "created_by": created_by,
            })
            data["skill_id"] = skill.id
        data["created_by"] = created_by
        obj = await self._repo.create(data)
        if obj.trigger_mode == "schedule" and obj.cron_expr:
            _register_patrol_schedule(obj.id, obj.cron_expr)
        return self._repo.to_response_dict(obj)

    async def update(self, patrol_id: int, body: AutoPatrolUpdate) -> Dict[str, Any]:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        steps = data.pop("steps_mapping", None)
        output_schema = data.pop("output_schema", None)

        obj = await self._repo.get_by_id(patrol_id)
        if not obj:
            raise ValueError(f"Auto-Patrol id={patrol_id} 不存在")

        # Update embedded skill if steps changed — only when patrol is skill-backed.
        input_schema = data.pop("input_schema", None)
        if steps is not None and obj.skill_id is not None:
            skill_repo = SkillDefinitionRepository(self._repo._db)
            skill_data: Dict[str, Any] = {"steps_mapping": steps}
            if input_schema is not None:
                skill_data["input_schema"] = input_schema
            if output_schema is not None:
                skill_data["output_schema"] = output_schema
            await skill_repo.update(obj.skill_id, skill_data)

        updated = await self._repo.update(patrol_id, data)
        if not updated:
            raise ValueError(f"Auto-Patrol id={patrol_id} 不存在")
        # Re-sync scheduler when trigger config changes
        _remove_patrol_schedule(patrol_id)
        if updated.trigger_mode == "schedule" and updated.cron_expr and updated.is_active:
            _register_patrol_schedule(updated.id, updated.cron_expr)
        return self._repo.to_response_dict(updated)

    async def delete(self, patrol_id: int) -> None:
        ok = await self._repo.delete(patrol_id)
        if not ok:
            raise ValueError(f"Auto-Patrol id={patrol_id} 不存在")

    # ── Execution ─────────────────────────────────────────────────────────────

    async def trigger(
        self,
        patrol_id: int,
        event_payload: Dict[str, Any],
        *,
        trigger_mode: str = "event",
    ) -> AutoPatrolTriggerResponse:
        """Run the patrol: execute skill → decide alarm.

        For schedule-triggered patrols with target_scope="all_equipment" or
        "equipment_list", fan-out: run Skill once per target equipment.
        """
        obj = await self._repo.get_by_id(patrol_id)
        if not obj:
            return AutoPatrolTriggerResponse(
                patrol_id=patrol_id, patrol_name="", skill_id=0,
                condition_met=False, alarm_created=False,
                error=f"Auto-Patrol id={patrol_id} 不存在",
            )

        logger.info(
            "AutoPatrol trigger patrol_id=%d skill_id=%s pipeline_id=%s trigger_mode=%s",
            patrol_id, obj.skill_id, getattr(obj, "pipeline_id", None), trigger_mode,
        )

        # ── Schedule: check if fan-out is needed ──────────────────────────────
        if trigger_mode == "schedule":
            target_scope = json.loads(obj.target_scope or '{"type":"event_driven"}')
            scope_type = target_scope.get("type", "event_driven")

            if scope_type in ("all_equipment", "equipment_list"):
                targets = await expand_to_targets(
                    target_scope=target_scope,
                    data_context=obj.data_context or "recent_ooc",
                    sim_url=self._sim_url,
                    db=self._repo._db,
                )
                if not targets:
                    return AutoPatrolTriggerResponse(
                        patrol_id=patrol_id, patrol_name=obj.name, skill_id=obj.skill_id,
                        condition_met=False, alarm_created=False,
                        error=f"No targets found for scope_type={scope_type}",
                    )
                logger.info("AutoPatrol fan-out: %d targets for patrol_id=%d", len(targets), patrol_id)
                results = []
                for target_payload in targets:
                    resp = await self._execute_single(obj, target_payload, trigger_mode)
                    results.append(resp)
                any_met = any(r.condition_met for r in results)
                any_alarm = any(r.alarm_created for r in results)
                return AutoPatrolTriggerResponse(
                    patrol_id=patrol_id, patrol_name=obj.name, skill_id=obj.skill_id,
                    condition_met=any_met, alarm_created=any_alarm,
                    findings={"fan_out_count": len(results), "condition_met_count": sum(1 for r in results if r.condition_met)},
                )

            # scope_type == "event_driven": build bulk context, single execution
            context = await build_schedule_context(
                data_context=obj.data_context or "recent_ooc",
                db=self._repo._db,
                sim_url=self._sim_url,
            )
        else:
            context = await build_event_context(event_payload)

        return await self._execute_single(obj, context, trigger_mode)

    async def _execute_single(
        self,
        obj,
        context: Dict[str, Any],
        trigger_mode: str,
    ) -> AutoPatrolTriggerResponse:
        """Execute once for a single context payload, write log, maybe create alarm.

        Phase 4-B: routes to pipeline path when `obj.pipeline_id` is set;
        otherwise falls back to the legacy skill execution path.
        """
        # New pipeline path — takes priority over legacy skill when both are set.
        if getattr(obj, "pipeline_id", None) is not None:
            return await self._execute_single_pipeline(obj, context, trigger_mode)

        import time
        log_repo = ExecutionLogRepository(self._repo._db)
        patrol_id = obj.id

        log_entry = await log_repo.create(
            skill_id=obj.skill_id,
            triggered_by=trigger_mode,
            event_context=context,
            auto_patrol_id=patrol_id,
        )
        t_start = time.monotonic()

        result = await self._executor.execute(
            skill_id=obj.skill_id,
            event_payload=context,
            triggered_by=f"auto_patrol:{patrol_id}:{trigger_mode}",
        )
        duration_ms = int((time.monotonic() - t_start) * 1000)

        if not result.success:
            logger.error("AutoPatrol skill execution failed: %s", result.error)
            await log_repo.finish(
                log_entry, status="error",
                error_message=result.error, duration_ms=duration_ms,
            )
            return AutoPatrolTriggerResponse(
                patrol_id=patrol_id, patrol_name=obj.name, skill_id=obj.skill_id,
                condition_met=False, alarm_created=False, error=result.error,
            )

        findings = result.findings
        condition_met = findings.condition_met if findings else False

        alarm_id: Optional[int] = None
        alarm_created = False

        if condition_met and obj.alarm_severity:
            try:
                equipment_id = str(context.get("equipment_id", ""))
                lot_id = str(context.get("lot_id", ""))
                step = context.get("step")
                event_time = context.get("event_time")
                summary = json.dumps(
                    findings.outputs if findings.outputs else findings.evidence,
                    ensure_ascii=False,
                ) if findings else None
                alarm = await self._alarm_repo.create(
                    skill_id=obj.skill_id,
                    trigger_event=f"auto_patrol:{patrol_id}",
                    equipment_id=equipment_id,
                    lot_id=lot_id,
                    step=step,
                    event_time=event_time,
                    severity=obj.alarm_severity,
                    title=obj.alarm_title or f"[Auto-Patrol] {obj.name}",
                    summary=summary,
                    execution_log_id=log_entry.id,
                )
                alarm_id = alarm.id
                alarm_created = True
                logger.info(
                    "AutoPatrol created alarm id=%d severity=%s patrol=%d equipment=%s",
                    alarm_id, obj.alarm_severity, patrol_id, equipment_id,
                )

                # Fan-out: trigger any Diagnostic Rules bound to this patrol
                await self._trigger_bound_diagnostic_rules(
                    patrol_id=patrol_id,
                    alarm_id=alarm_id,
                    alarm_context=context,
                )

                # Phase 5-UX-7: Fan-out to auto_check pipelines bound to this
                # alarm's trigger_event. Inputs auto-resolved from alarm payload
                # by name-match (see auto_check_dispatcher).
                try:
                    from app.services.auto_check_dispatcher import dispatch_alarm_to_auto_checks
                    alarm_payload = dict(context or {})
                    alarm_payload.setdefault("tool_id", equipment_id)
                    alarm_payload.setdefault("lot_id", lot_id)
                    alarm_payload.setdefault("step", step)
                    alarm_payload.setdefault("event_time", event_time)
                    await dispatch_alarm_to_auto_checks(
                        self._repo._db,
                        alarm_id=alarm_id,
                        trigger_event=f"auto_patrol:{patrol_id}",
                        alarm_payload=alarm_payload,
                    )
                except Exception as disp_exc:  # noqa: BLE001
                    logger.warning(
                        "auto_check dispatch from auto_patrol alarm %s failed (non-blocking): %s",
                        alarm_id, disp_exc,
                    )
            except Exception as exc:
                logger.exception("AutoPatrol failed to create alarm: %s", exc)

        await log_repo.finish(
            log_entry,
            status="success",
            llm_readable_data=findings.model_dump() if findings else None,
            action_dispatched=f"alarm:{alarm_id}" if alarm_id else None,
            duration_ms=duration_ms,
        )

        return AutoPatrolTriggerResponse(
            patrol_id=patrol_id, patrol_name=obj.name, skill_id=obj.skill_id,
            condition_met=condition_met, alarm_created=alarm_created,
            alarm_id=alarm_id,
            findings=findings.model_dump() if findings else None,
        )

    async def _execute_single_pipeline(
        self,
        obj,
        context: Dict[str, Any],
        trigger_mode: str,
    ) -> AutoPatrolTriggerResponse:
        """Phase 4-B: execute a Pipeline (instead of Skill), decide alarm from result_summary.

        Flow:
          1. Load pipeline_json from pb_pipelines
          2. Resolve input_binding against `context` → concrete inputs dict
          3. PipelineExecutor.execute(pipeline_json, inputs=resolved)
          4. result_summary.triggered → alarm decision
          5. Evidence rows from terminal logic node → alarm.summary
        """
        import json as _json
        import time
        from app.models.pipeline import PipelineModel
        from app.repositories.pipeline_repository import PipelineRepository, PipelineRunRepository
        from app.services.pipeline_builder.block_registry import BlockRegistry
        from app.services.pipeline_builder.executor import PipelineExecutor
        from app.schemas.pipeline import PipelineJSON

        log_repo = ExecutionLogRepository(self._repo._db)
        pipeline_repo = PipelineRepository(self._repo._db)
        patrol_id = obj.id
        pipeline_id = obj.pipeline_id

        log_entry = await log_repo.create(
            skill_id=None,
            triggered_by=trigger_mode,
            event_context=context,
            auto_patrol_id=patrol_id,
        )
        t_start = time.monotonic()

        pipeline_row = await pipeline_repo.get_by_id(pipeline_id)
        if pipeline_row is None:
            err = f"Pipeline {pipeline_id} not found"
            await log_repo.finish(log_entry, status="error", error_message=err,
                                  duration_ms=int((time.monotonic() - t_start) * 1000))
            return AutoPatrolTriggerResponse(
                patrol_id=patrol_id, patrol_name=obj.name, skill_id=None,
                condition_met=False, alarm_created=False, error=err,
            )
        try:
            pipeline_json = PipelineJSON.model_validate(_json.loads(pipeline_row.pipeline_json))
        except Exception as e:
            err = f"Invalid pipeline JSON: {e}"
            await log_repo.finish(log_entry, status="error", error_message=err,
                                  duration_ms=int((time.monotonic() - t_start) * 1000))
            return AutoPatrolTriggerResponse(
                patrol_id=patrol_id, patrol_name=obj.name, skill_id=None,
                condition_met=False, alarm_created=False, error=err,
            )

        # Resolve input bindings from patrol config + runtime context
        binding = self._repo.get_input_binding(obj)
        resolved_inputs = _resolve_input_binding(binding, context)

        # Build registry + execute
        registry = BlockRegistry()
        await registry.load_from_db(self._repo._db)
        executor = PipelineExecutor(registry)
        run_repo = PipelineRunRepository(self._repo._db)
        run = await run_repo.create_run(
            pipeline_id=pipeline_id,
            pipeline_version=pipeline_row.version or "1.0.0",
            triggered_by="schedule" if trigger_mode == "schedule" else "event",
            status="running",
        )
        await self._repo._db.commit()

        try:
            result = await executor.execute(pipeline_json, run_id=run.id, inputs=resolved_inputs)
        except Exception as exc:
            logger.exception("AutoPatrol pipeline execution crashed: %s", exc)
            err = f"{type(exc).__name__}: {exc}"
            await run_repo.finish_run(
                run_id=run.id, status="failed", node_results={},
                error_message=err,
            )
            await log_repo.finish(log_entry, status="error", error_message=err,
                                  duration_ms=int((time.monotonic() - t_start) * 1000))
            await self._repo._db.commit()
            return AutoPatrolTriggerResponse(
                patrol_id=patrol_id, patrol_name=obj.name, skill_id=None,
                condition_met=False, alarm_created=False, error=err,
            )

        await run_repo.finish_run(
            run_id=run.id, status=result["status"],
            node_results=result["node_results"],
            error_message=result.get("error_message"),
        )
        duration_ms = int((time.monotonic() - t_start) * 1000)

        summary = result.get("result_summary") or {}
        condition_met = bool(summary.get("triggered", False))

        # PR-C telemetry — bump usage_stats on successful execution
        if result["status"] == "success":
            try:
                await pipeline_repo.bump_usage_stats(pipeline_id, triggered=condition_met)
            except Exception as _tex:  # noqa: BLE001
                logger.warning("usage_stats bump failed for pipeline %s: %s", pipeline_id, _tex)

        alarm_id: Optional[int] = None
        alarm_created = False
        if condition_met and obj.alarm_severity:
            try:
                equipment_id = str(context.get("equipment_id") or context.get("tool_id") or "")
                lot_id = str(context.get("lot_id", ""))
                # Pull evidence preview from the terminal logic node's preview rows.
                # PR-A: evidence now contains ALL evaluated rows with a
                # `triggered_row` boolean column — for alarm summaries we only
                # want the rows that actually fired, so filter on that column.
                # Falls back to full rows if column absent (older blocks).
                ev_node_id = summary.get("evidence_node_id")
                evidence_preview = None
                if ev_node_id and ev_node_id in result["node_results"]:
                    ev_port = (result["node_results"][ev_node_id].get("preview") or {}).get("evidence")
                    if ev_port:
                        rows = ev_port.get("rows") or []
                        columns = ev_port.get("columns")
                        if rows and "triggered_row" in (columns or []):
                            filtered = [r for r in rows if r.get("triggered_row")]
                            # Prefer filtered view but fall back if nothing matched
                            if filtered:
                                rows = filtered
                        evidence_preview = {
                            "columns": columns,
                            "rows": rows[:20],
                            "total": len(rows),
                        }
                alarm = await self._alarm_repo.create(
                    skill_id=None,
                    trigger_event=f"auto_patrol:{patrol_id}",
                    equipment_id=equipment_id,
                    lot_id=lot_id,
                    step=context.get("step"),
                    event_time=context.get("event_time"),
                    severity=obj.alarm_severity,
                    title=obj.alarm_title or f"[Auto-Patrol] {obj.name}",
                    summary=_json.dumps(evidence_preview, ensure_ascii=False) if evidence_preview else None,
                    execution_log_id=log_entry.id,
                )
                alarm_id = alarm.id
                alarm_created = True
                logger.info(
                    "AutoPatrol (pipeline) created alarm id=%d severity=%s patrol=%d pipeline=%d",
                    alarm_id, obj.alarm_severity, patrol_id, pipeline_id,
                )
                await self._trigger_bound_diagnostic_rules(
                    patrol_id=patrol_id, alarm_id=alarm_id, alarm_context=context,
                )
            except Exception as exc:
                logger.exception("AutoPatrol (pipeline) failed to create alarm: %s", exc)

        await log_repo.finish(
            log_entry,
            status="success",
            llm_readable_data=summary or None,
            action_dispatched=f"alarm:{alarm_id}" if alarm_id else None,
            duration_ms=duration_ms,
        )
        await self._repo._db.commit()

        return AutoPatrolTriggerResponse(
            patrol_id=patrol_id, patrol_name=obj.name, skill_id=None,
            condition_met=condition_met, alarm_created=alarm_created,
            alarm_id=alarm_id,
            findings={"pipeline_id": pipeline_id, "result_summary": summary},
        )

    async def _trigger_bound_diagnostic_rules(
        self,
        patrol_id: int,
        alarm_id: int,
        alarm_context: Dict[str, Any],
    ) -> None:
        """Find all Diagnostic Rules bound to this patrol and execute them.

        Results are stored in ExecutionLog and linked back to the alarm
        via alarm.diagnostic_log_id.
        """
        from sqlalchemy import select
        from app.models.skill_definition import SkillDefinitionModel

        try:
            result = await self._repo._db.execute(
                select(SkillDefinitionModel)
                .where(SkillDefinitionModel.trigger_patrol_id == patrol_id)
                .where(SkillDefinitionModel.is_active == True)  # noqa: E712
                .where(SkillDefinitionModel.source == "rule")
            )
            dr_skills = result.scalars().all()
            if not dr_skills:
                return

            log_repo = ExecutionLogRepository(self._repo._db)
            for dr in dr_skills:
                via_pipeline = dr.pipeline_id is not None
                logger.info(
                    "DR fan-out: running skill_id=%d pipeline_id=%s (DR '%s') for alarm_id=%d",
                    dr.id, dr.pipeline_id, dr.name, alarm_id,
                )
                try:
                    dr_log = await log_repo.create(
                        skill_id=dr.id,
                        triggered_by=f"alarm:{alarm_id}",
                        event_context=alarm_context,
                        auto_patrol_id=None,
                    )
                    import time as _time
                    t0 = _time.monotonic()
                    if via_pipeline:
                        dr_result = await run_dr_via_pipeline(
                            self._repo._db, dr, alarm_id, alarm_context,
                        )
                        status = "success" if dr_result["success"] else "error"
                        findings = dr_result["findings"]
                        error_msg = dr_result["error"]
                    else:
                        legacy = await self._executor.execute(
                            skill_id=dr.id,
                            event_payload=alarm_context,
                            triggered_by=f"alarm:{alarm_id}",
                        )
                        status = "success" if legacy.success else "error"
                        findings = legacy.findings.model_dump() if legacy.findings else None
                        error_msg = legacy.error
                    dur = int((_time.monotonic() - t0) * 1000)
                    await log_repo.finish(
                        dr_log,
                        status=status,
                        llm_readable_data=findings,
                        error_message=error_msg,
                        duration_ms=dur,
                    )
                    # Link the DR log back to the alarm
                    await self._alarm_repo.set_diagnostic_log(alarm_id, dr_log.id)
                    logger.info(
                        "DR fan-out done: skill_id=%d alarm_id=%d dr_log_id=%d via_pipeline=%s condition_met=%s",
                        dr.id, alarm_id, dr_log.id, via_pipeline,
                        findings.get("condition_met") if findings else False,
                    )
                except Exception as exc:
                    logger.exception("DR fan-out failed for skill_id=%d: %s", dr.id, exc)
        except Exception as exc:
            logger.exception("DR fan-out query failed patrol_id=%d: %s", patrol_id, exc)

    async def trigger_by_event(
        self,
        event_type_id: int,
        event_payload: Dict[str, Any],
    ) -> List[AutoPatrolTriggerResponse]:
        """Called when a system event arrives — fan-out to all matching patrols."""
        patrols = await self._repo.list_by_event_type(event_type_id)
        if not patrols:
            return []
        results = []
        for patrol in patrols:
            resp = await self.trigger(patrol.id, event_payload, trigger_mode="event")
            results.append(resp)
        return results

    async def trigger_by_schedule(self, patrol_id: int) -> AutoPatrolTriggerResponse:
        """Called by APScheduler — builds context from DB/OntologySimulator then runs Skill."""
        return await self.trigger(patrol_id, {}, trigger_mode="schedule")


# ── APScheduler helpers (module-level) ───────────────────────────────────────

def _register_patrol_schedule(patrol_id: int, cron_expr: str) -> None:
    """Register a schedule-mode patrol in APScheduler."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        from app.services.cron_scheduler_service import get_scheduler
        sched = get_scheduler()
        if not sched.running:
            logger.warning("Scheduler not running — patrol %d will be loaded on next startup", patrol_id)
            return
        trigger = CronTrigger.from_crontab(cron_expr, timezone="UTC")
        sched.add_job(
            _run_scheduled_patrol,
            trigger=trigger,
            id=f"patrol_{patrol_id}",
            kwargs={"patrol_id": patrol_id},
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Registered schedule patrol id=%d cron='%s'", patrol_id, cron_expr)
    except Exception as exc:
        logger.error("Failed to register patrol schedule id=%d: %s", patrol_id, exc)


def _remove_patrol_schedule(patrol_id: int) -> None:
    try:
        from app.services.cron_scheduler_service import get_scheduler
        get_scheduler().remove_job(f"patrol_{patrol_id}")
    except Exception:
        pass


async def _run_scheduled_patrol(patrol_id: int) -> None:
    """Standalone async runner called by APScheduler for schedule-triggered patrols."""
    from app.database import AsyncSessionLocal
    from app.config import get_settings
    from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor

    async with AsyncSessionLocal() as db:
        settings = get_settings()
        executor = SkillExecutorService(
            skill_repo=SkillDefinitionRepository(db),
            mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
        )
        svc = AutoPatrolService(
            repo=AutoPatrolRepository(db),
            alarm_repo=AlarmRepository(db),
            executor=executor,
            sim_url=settings.ONTOLOGY_SIM_URL,
        )
        try:
            resp = await svc.trigger_by_schedule(patrol_id)
            logger.info(
                "Scheduled patrol id=%d condition_met=%s alarm_created=%s",
                patrol_id, resp.condition_met, resp.alarm_created,
            )
        except Exception as exc:
            logger.exception("Scheduled patrol id=%d failed: %s", patrol_id, exc)


async def load_schedule_patrols_into_scheduler(db: AsyncSession) -> None:
    """Called on app startup — re-register all active schedule-mode patrols."""
    from sqlalchemy import select
    from app.models.auto_patrol import AutoPatrolModel

    result = await db.execute(
        select(AutoPatrolModel)
        .where(AutoPatrolModel.trigger_mode == "schedule")
        .where(AutoPatrolModel.is_active == True)  # noqa: E712
        .where(AutoPatrolModel.cron_expr.isnot(None))
    )
    patrols = result.scalars().all()
    for p in patrols:
        _register_patrol_schedule(p.id, p.cron_expr)
    logger.info("Loaded %d schedule-mode patrols into scheduler", len(patrols))
