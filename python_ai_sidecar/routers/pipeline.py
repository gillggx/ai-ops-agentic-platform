"""Pipeline Executor endpoints.

Phase 5a: /execute goes live — fetches the pipeline from Java, pretends to
run it (minimal echo executor), and writes an execution_log row back via Java.
This proves the reverse-auth round-trip. Phase 5c swaps the echo for
``fastapi_backend_service.app.services.pipeline_executor``.
"""

from __future__ import annotations

import json
import logging
import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth import CallerContext, ServiceAuth
from ..clients.java_client import JavaAPIClient, JavaAPIError
from ..executor.block_runtime import REGISTRY as BLOCK_REGISTRY
from ..executor.dag import execute_dag
from ..executor.real_executor import (
    SIDECAR_NATIVE_BLOCKS,
    all_blocks_native,
    execute_native,
)

log = logging.getLogger("python_ai_sidecar.pipeline")
router = APIRouter(prefix="/internal/pipeline", tags=["pipeline"])


class ExecuteRequest(BaseModel):
    pipeline_id: int | None = None
    pipeline_json: dict | None = None
    inputs: dict[str, Any] | None = None
    triggered_by: str = "user"
    # 2026-06-26: forwarded by SkillStepExecutor.runOneStep so the
    # execution_logs row carries the same provenance as the parent
    # skill_runs row (skill_id + JSON event_context). Optional — ad-hoc
    # builder previews still send neither.
    skill_id: int | None = None
    event_context: str | None = None


class ValidateRequest(BaseModel):
    pipeline_json: dict


class PreviewRequest(BaseModel):
    """Run pipeline up to (and including) `node_id` and return that node's
    preview rows. Does NOT persist a PipelineRun. Mirrors the old
    fastapi-backend's POST /api/v1/pipeline-builder/preview that the
    Builder's RUN PREVIEW button used before the Java cutover."""
    pipeline_json: dict
    node_id: str
    sample_size: int = 100
    inputs: dict[str, Any] | None = None


def _node_count(pipeline_json: dict | None) -> int:
    if not isinstance(pipeline_json, dict):
        return 0
    nodes = pipeline_json.get("nodes")
    return len(nodes) if isinstance(nodes, list) else 0


async def _resolve_pipeline(java: JavaAPIClient, req: ExecuteRequest) -> tuple[dict | None, dict | None]:
    """Return (pipeline_entity_from_java, effective_json_to_execute).

    Rules:
      - If pipeline_id given, fetch from Java (source of truth).
      - Else if pipeline_json given, use that (ad-hoc run, no persisted record).
      - Else return (None, None).
    """
    if req.pipeline_id is not None:
        try:
            entity = await java.get_pipeline(req.pipeline_id)
        except JavaAPIError as ex:
            if ex.status == 404:
                raise HTTPException(status_code=404, detail=f"pipeline {req.pipeline_id} not found in Java")
            raise
        # JavaAPIClient._request normalises response keys to snake_case, so
        # the field we get back is `pipeline_json` (not the Java-side
        # camelCase `pipelineJson`). Reading the camelCase key returned None
        # and made the executor see an empty {} → "pipeline_json failed
        # schema validation" 500 (caught 2026-04-28 during pipeline audit).
        raw = entity.get("pipeline_json") or entity.get("pipelineJson")
        effective = json.loads(raw) if isinstance(raw, str) and raw else raw
        return entity, effective if isinstance(effective, dict) else {}
    if req.pipeline_json is not None:
        return None, req.pipeline_json
    return None, None


@router.post("/execute")
async def execute(req: ExecuteRequest, caller: CallerContext = ServiceAuth) -> dict:
    """Execute a pipeline.

    Decision tree:
      1. If all blocks are in SIDECAR_NATIVE_BLOCKS → Phase 8-B native
         executor (full pandas DAG, validator, RunCache, etc.)
      2. Else → legacy 6-block demo walker (kept as safety net + for the
         sub-set of tests that depend on it).

    The :8001 fallback proxy was retired in 2026-05-02 cleanup; native
    executor covers all 47 production blocks, and the legacy walker still
    catches test-only fake blocks like load_inline_rows.
    """
    java = JavaAPIClient.for_caller(caller)
    entity, effective = await _resolve_pipeline(java, req)

    # Phase 8-B fast path: everything in whitelist → native executor.
    if isinstance(effective, dict) and all_blocks_native(effective):
        started = time.monotonic()
        try:
            result = await execute_native(
                effective,
                inputs=req.inputs,
                run_id=req.pipeline_id,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            status = result.get("status") or "error"
            # Java Jackson uses SNAKE_CASE — send snake_case keys.
            persisted = await java.create_execution_log({
                "triggered_by": req.triggered_by or "user",
                "skill_id": req.skill_id,
                "event_context": req.event_context,
                "status": "success" if status == "success" else "error",
                "llm_readable_data": json.dumps({
                    "source": "python_ai_sidecar_native",
                    "pipeline_id": req.pipeline_id,
                    "status": status,
                    "node_results": result.get("node_results") or {},
                    "result_summary": result.get("result_summary"),
                    "inputs_echo": {k: str(v)[:100] for k, v in (req.inputs or {}).items()},
                }, ensure_ascii=False, default=str),
                "duration_ms": duration_ms,
                "error_message": result.get("error_message"),
            })
            return {
                "ok": status == "success",
                "execution_log_id": persisted.get("id") if isinstance(persisted, dict) else None,
                "caller_user_id": caller.user_id,
                "pipeline": {
                    "id": entity.get("id") if entity else None,
                    "name": entity.get("name") if entity else None,
                    "resolved": entity is not None or effective is not None,
                },
                "status": status,
                "source": "native",
                "node_results": result.get("node_results") or {},
                "result_summary": result.get("result_summary"),
                "duration_ms": duration_ms,
            }
        except Exception as ex:  # noqa: BLE001
            log.exception("native executor failed")
            raise HTTPException(
                status_code=500,
                detail={"code": "native_executor_failed", "message": str(ex)[:300]},
            )

    # Safety net: legacy demo walker (used by /validate tests that pass
    # fake blocks like load_inline_rows). For non-native real-world blocks
    # this will fail and the caller sees an error — the :8001 fallback was
    # retired since native executor covers all production blocks.
    started = time.monotonic()
    try:
        walk = execute_dag(effective)
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "success" if walk.get("status") == "success" else "error"
        persisted = await java.create_execution_log({
            "triggered_by": req.triggered_by or "user",
            "skill_id": req.skill_id,
            "event_context": req.event_context,
            "status": status,
            "llm_readable_data": json.dumps({
                "source": "python_ai_sidecar_demo",
                "pipeline_id": req.pipeline_id,
                "node_results": walk.get("node_results") or {},
                "terminal_nodes": walk.get("terminal_nodes") or [],
                "preview": walk.get("preview") or [],
                "inputs_echo": {k: str(v)[:100] for k, v in (req.inputs or {}).items()},
            }, ensure_ascii=False),
            "duration_ms": duration_ms,
            "error_message": walk.get("reason") if walk.get("status") == "validation_error" else None,
        })
        return {
            "ok": status == "success",
            "execution_log_id": persisted.get("id") if isinstance(persisted, dict) else None,
            "caller_user_id": caller.user_id,
            "pipeline": {
                "id": entity.get("id") if entity else None,
                "name": entity.get("name") if entity else None,
                "resolved": entity is not None or effective is not None,
            },
            "status": status,
            "source": "demo",
            "node_results": walk.get("node_results") or {},
            "preview": walk.get("preview") or [],
            "duration_ms": duration_ms,
        }
    except JavaAPIError as ex:
        log.exception("Java API failed during /execute")
        raise HTTPException(status_code=502, detail={
            "code": "java_api_error", "status": ex.status, "message": ex.message,
        })


@router.post("/validate")
async def validate(req: ValidateRequest, caller: CallerContext = ServiceAuth) -> dict:
    """Dry-run the DAG walker: topo-sort + block lookup without any I/O.
    Surfaces unknown blocks, cycles, and orphan edges before Frontend
    commits the pipeline."""
    try:
        walk = execute_dag(req.pipeline_json)
    except Exception as ex:  # noqa: BLE001 — DAGError on cycle, malformed JSON etc.
        return {
            "ok": False,
            "status": "validation_error",
            "error": str(ex)[:300],
            "caller_user_id": caller.user_id,
        }
    node_results = walk.get("node_results") or {}
    errors = [
        {"node_id": nid, "error": r.get("error")}
        for nid, r in node_results.items() if r.get("status") == "error"
    ]
    return {
        "ok": walk.get("status") == "success",
        "status": walk.get("status"),
        "node_count": len(node_results),
        "errors": errors,
        "terminal_nodes": walk.get("terminal_nodes") or [],
        "caller_user_id": caller.user_id,
    }


@router.post("/preview")
async def preview(req: PreviewRequest, caller: CallerContext = ServiceAuth) -> dict:
    """Truncate pipeline to ancestors of {node_id}, run them, return the
    target node's rows. Used by Builder's RUN PREVIEW button so the user
    can inspect a node's output mid-design without saving the pipeline.

    Inputs default to each declared input's `example` value when caller
    didn't supply one — same behavior as the old fastapi-backend route
    so a fresh draft pipeline previews cleanly without manual binding."""
    pipeline_json = req.pipeline_json or {}
    nodes = pipeline_json.get("nodes") or []
    edges = pipeline_json.get("edges") or []
    node_ids = {n.get("id") for n in nodes if n.get("id")}
    target = req.node_id
    if target not in node_ids:
        raise HTTPException(status_code=404, detail=f"node '{target}' not in pipeline")

    # BFS upstream from target collecting ancestors (inclusive).
    ancestors = {target}
    frontier = {target}
    while frontier:
        next_frontier: set[str] = set()
        for e in edges:
            from_node = (e.get("from") or {}).get("node")
            to_node = (e.get("to") or {}).get("node")
            if to_node in frontier and from_node and from_node not in ancestors:
                ancestors.add(from_node)
                next_frontier.add(from_node)
        frontier = next_frontier

    truncated_dict = {
        **pipeline_json,
        "nodes": [n for n in nodes if n.get("id") in ancestors],
        "edges": [
            e for e in edges
            if (e.get("from") or {}).get("node") in ancestors
               and (e.get("to") or {}).get("node") in ancestors
        ],
    }

    # Pydantic-parse the truncated subgraph; if it fails we surface the
    # exception text rather than 500-ing.
    from python_ai_sidecar.pipeline_builder.executor import PipelineJSON
    try:
        pipeline = PipelineJSON.model_validate(truncated_dict)
    except Exception as ex:  # noqa: BLE001
        return {
            "status": "validation_error",
            "errors": [{"rule": "PARSE", "message": str(ex)[:400]}],
            "caller_user_id": caller.user_id,
        }

    # Default each declared input's value to its `example` if caller didn't
    # provide one — keeps the preview useful on a fresh draft.
    preview_inputs = dict(req.inputs or {})
    for decl in pipeline.inputs or []:
        name = getattr(decl, "name", None)
        if not name:
            continue
        if preview_inputs.get(name) is None:
            example = getattr(decl, "example", None)
            if example is not None:
                preview_inputs[name] = example

    from python_ai_sidecar.executor.real_executor import get_real_executor
    executor = get_real_executor()
    try:
        result = await executor.execute(
            pipeline,
            preview_sample_size=req.sample_size,
            inputs=preview_inputs,
        )
    except Exception as ex:  # noqa: BLE001
        log.exception("preview executor failed")
        return {
            "status": "error",
            "error_message": f"executor failed: {ex}"[:400],
            "caller_user_id": caller.user_id,
        }

    node_results = result.get("node_results") or {}
    target_result = node_results.get(target)
    return {
        "status": result.get("status", "success"),
        "target": target,
        "node_result": target_result,
        "all_node_results": node_results,
        "result_summary": result.get("result_summary"),
        "caller_user_id": caller.user_id,
    }


# ── Skill 參數化 + 說明書 (真 Skill 化, 2026-07-08) ─────────────────────────

class ParameterizeRequest(BaseModel):
    pipeline_json: dict
    # 空 accept → 只回候選清單；有 accept → 回套用後的 pipeline
    accept: list[str] | None = None


@router.post("/parameterize")
async def parameterize(req: ParameterizeRequest, caller: CallerContext = ServiceAuth) -> dict:
    """真 Skill 化 F1: source 身分參數 → 宣告式 inputs（$name）。
    候選辨識與套用皆為確定性（parameterize.py 純函式，有單元測試）。"""
    from python_ai_sidecar.pipeline_builder.parameterize import (
        apply_parameterize, find_candidates,
    )
    if not req.accept:
        return {"candidates": find_candidates(req.pipeline_json)}
    patched, err = apply_parameterize(req.pipeline_json, req.accept)
    if patched is None:
        raise HTTPException(status_code=422, detail=err)
    return {"pipeline_json": patched,
            "inputs": patched.get("inputs") or []}


class DraftDocRequest(BaseModel):
    name: str
    nl: str = ""
    pipeline_json: dict
    siblings: list[dict] | None = None  # [{name, use_case}] 供「與相似 skill 區別」


@router.post("/skill-draft-doc")
async def skill_draft_doc(req: DraftDocRequest, caller: CallerContext = ServiceAuth) -> dict:
    """真 Skill 化 F2: 草擬 skill 說明書（做什麼/輸入/輸出/何時用+區別）。
    裁決 2: 固定用 Haiku（同 V54 慣例，可由 env SKILL_DOC_LLM_MODEL 覆蓋）。
    草稿必須經人編修後儲存 — 這裡只產草稿。"""
    import os as _os
    from python_ai_sidecar.agent_helpers_native.llm_client import AnthropicLLMClient
    from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings

    settings = get_settings()
    model = _os.environ.get("SKILL_DOC_LLM_MODEL", "claude-haiku-4-5-20251001")
    client = AnthropicLLMClient(api_key=settings.ANTHROPIC_API_KEY, model=model)

    inputs = req.pipeline_json.get("inputs") or []
    nodes = [{"id": n.get("id"), "block": n.get("block_id"), "params": n.get("params")}
             for n in (req.pipeline_json.get("nodes") or [])]
    system = (
        "你是技術文件作者。為一個資料分析 Skill 草擬說明書（JSON），"
        "讀者是「要選用 skill 的 agent 與工程師」。輸出：\n"
        '{"use_case": "一句話說這個 skill 做什麼、輸出什麼",\n'
        ' "when_to_use": ["情境1", "情境2", "…max 4 — 什麼樣的問題該用它"],\n'
        ' "distinction": "與相似 skill 的區別（若提供了 siblings）；沒有就寫它的獨特點",\n'
        ' "example_invocation": {"inputs": {…用 inputs 的實際名稱與 example 值…}},\n'
        ' "tags": ["…max 5 檢索關鍵字（中英混合）"]}\n'
        "規則：寫能力與時機，不寫 block 名；inputs 名稱必須與宣告一致；只輸出 JSON。"
    )
    user = json.dumps({
        "name": req.name, "nl": req.nl,
        "inputs": inputs, "nodes": nodes,
        "siblings": (req.siblings or [])[:8],
    }, ensure_ascii=False, default=str)[:5000]
    try:
        resp = await client.create(system=system,
                                   messages=[{"role": "user", "content": user}],
                                   max_tokens=900)
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        doc = json.loads(raw)
    except Exception as ex:  # noqa: BLE001
        log.warning("skill_draft_doc: LLM failed: %s", ex)
        raise HTTPException(status_code=502, detail=f"doc draft failed: {ex}"[:200])
    if not isinstance(doc, dict) or not doc.get("use_case"):
        raise HTTPException(status_code=502, detail="doc draft unusable")
    return {"doc": doc, "model": model}


# ── Full-data CSV export (2026-07-07) ─────────────────────────────────────
# UI tables ship at most ~100 rows for render performance; users who need
# the complete dataset download it here instead. Re-executes the subgraph
# on demand (no server-side result persistence — EC2 disk is tight), so the
# exported rows are as-of download time, not as-of the original run.

_EXPORT_ROWS_CAP = 200_000  # OOM guard for the 8GB box; well past any real use


class ExportCsvRequest(BaseModel):
    pipeline_json: dict
    node_id: str
    inputs: dict[str, Any] | None = None


@router.post("/export-csv")
async def export_csv(req: ExportCsvRequest, caller: CallerContext = ServiceAuth):
    """Run the subgraph up to `node_id` with FULL rows and stream the target
    node's dataframe output as CSV.

    block_data_view caps its own `rows` by its max_rows param, so exporting
    a data_view node silently truncates — redirect to its upstream source
    node (the data the view renders) instead."""
    import csv as _csv
    import io as _io
    from fastapi.responses import StreamingResponse

    pipeline_json = req.pipeline_json or {}
    nodes = pipeline_json.get("nodes") or []
    edges = pipeline_json.get("edges") or []
    target = req.node_id

    node_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    if target not in node_by_id:
        raise HTTPException(status_code=404, detail=f"node '{target}' not in pipeline")
    if (node_by_id[target].get("block_id") or "") == "block_data_view":
        upstream = [
            (e.get("from") or {}).get("node")
            for e in edges
            if (e.get("to") or {}).get("node") == target
        ]
        if upstream and upstream[0] in node_by_id:
            target = upstream[0]

    result = await preview(
        PreviewRequest(
            pipeline_json=pipeline_json,
            node_id=target,
            sample_size=_EXPORT_ROWS_CAP,
            inputs=req.inputs,
        ),
        caller,
    )
    if result.get("status") not in ("success", "partial"):
        detail = (
            result.get("error_message")
            or "; ".join(e.get("message", "") for e in (result.get("errors") or []))
            or f"status={result.get('status')}"
        )
        raise HTTPException(status_code=422, detail=detail[:400])

    preview_blob = (result.get("node_result") or {}).get("preview") or {}
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    for _port, blob in preview_blob.items():
        if isinstance(blob, dict) and blob.get("type") == "dataframe":
            columns = list(blob.get("columns") or [])
            rows = list(blob.get("rows") or [])
            break
    if not columns:
        raise HTTPException(
            status_code=422,
            detail=f"node '{target}' produced no dataframe output to export",
        )

    def _cell(v: Any) -> Any:
        # nested dict/list cells → JSON text so the CSV stays rectangular
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v

    def _iter_csv():
        buf = _io.StringIO()
        writer = _csv.writer(buf)
        buf.write("\ufeff")  # UTF-8 BOM (explicit escape) so Excel opens CJK correctly
        writer.writerow(columns)
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for i, r in enumerate(rows):
            writer.writerow([_cell(r.get(c)) for c in columns])
            if (i + 1) % 500 == 0:
                yield buf.getvalue()
                buf.seek(0); buf.truncate(0)
        if buf.tell():
            yield buf.getvalue()

    log.info("export_csv: node=%s rows=%d cols=%d user=%s",
             target, len(rows), len(columns), caller.user_id)
    return StreamingResponse(
        _iter_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{target}.csv"'},
    )


class TryRunRequest(BaseModel):
    pipeline_json: dict
    inputs: dict | None = None


@router.post("/tryrun")
async def tryrun(req: TryRunRequest, caller: CallerContext = ServiceAuth) -> dict:
    """My Drafts (2026-07-12)：草稿卡的 Try Run — 跑一次並回「瘦身」結果
    （圖卡 + 節點摘要），手機/對話內直接渲染，不回完整 node_results。"""
    import time as _time

    from python_ai_sidecar.executor.real_executor import get_real_executor
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
    from python_ai_sidecar.routers.agent import _slim_chart_spec, _spc_limits_to_rules

    executor = get_real_executor()
    pj_model = PipelineJSON.model_validate(req.pipeline_json)
    t0 = _time.perf_counter()
    try:
        result = await asyncio.wait_for(
            executor.execute(pj_model, inputs=req.inputs or {}), timeout=45.0)
    except asyncio.TimeoutError:
        return {"status": "timeout", "error": "try run 超過 45 秒", "charts": [], "nodes": []}
    duration_ms = int((_time.perf_counter() - t0) * 1000)

    node_results = (result or {}).get("node_results") or {}
    nodes = []
    charts: list[dict] = []
    for nid, info in node_results.items():
        if not isinstance(info, dict):
            continue
        nodes.append({"id": nid, "status": info.get("status"),
                      "rows": info.get("rows"),
                      "error": (str(info.get("error"))[:200] if info.get("error") else None)})
        ports = info.get("preview") or {}
        for _port, blob in ports.items():
            if not isinstance(blob, dict):
                continue
            snap = blob.get("snapshot")
            if isinstance(snap, dict) and isinstance(snap.get("data"), list) and isinstance(snap.get("type"), str):
                charts.append({"node_id": nid, "chart_spec": _slim_chart_spec(snap)})
                continue
            sample = blob.get("sample")
            if blob.get("type") == "list" and isinstance(sample, list):
                for ci, spec in enumerate(sample[:8]):
                    if isinstance(spec, dict) and spec.get("__dsl"):
                        charts.append({"node_id": f"{nid}#{ci}",
                                       "chart_spec": _slim_chart_spec(_spc_limits_to_rules(spec))})
    ok = all(n.get("status") == "success" for n in nodes) if nodes else False
    return {"status": "success" if ok else "failed", "duration_ms": duration_ms,
            "charts": charts[:10], "nodes": nodes}
