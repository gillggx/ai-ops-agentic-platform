"""Pipeline Executor — DAG topological sort + async node execution.

Phase 1 scope:
  - Single run, single worker.
  - Stops downstream on any upstream failure (fail-fast).
  - Records per-node results (status, rows, duration, error, preview).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutionError, ExecutionContext
from python_ai_sidecar.pipeline_builder.cache import RunCache

logger = logging.getLogger(__name__)

_PREVIEW_ROWS_DEFAULT = 100  # reasonable UI upper bound; /preview accepts sample_size override
_PREVIEW_MAX_COLS = 30


# Phase 4-B0: pipeline inputs resolver ---------------------------------------

def _coerce_input(value: Any, declared_type: str) -> Any:
    """Coerce a provided input value to its declared type. Raises ValueError on failure."""
    if value is None:
        return None
    if declared_type == "string":
        return str(value)
    if declared_type == "integer":
        if isinstance(value, bool):  # bool is subclass of int — avoid silent confusion
            raise ValueError(f"got bool, expected integer")
        return int(value)
    if declared_type == "number":
        if isinstance(value, bool):
            raise ValueError(f"got bool, expected number")
        return float(value)
    if declared_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low in {"true", "1", "yes"}:
                return True
            if low in {"false", "0", "no"}:
                return False
        raise ValueError(f"cannot coerce {value!r} to boolean")
    return value  # unknown type → pass through


def _resolve_inputs(pipeline: PipelineJSON, runtime_inputs: dict[str, Any]) -> dict[str, Any]:
    """Merge runtime values with pipeline.inputs defaults; enforce required; coerce types.

    Returns a single `{name: resolved_value}` dict used by _resolve_params.
    Raises BlockExecutionError (MISSING_INPUT / INVALID_INPUT) on missing required or coercion failure.
    """
    resolved: dict[str, Any] = {}
    declared = getattr(pipeline, "inputs", None) or []
    known_names: set[str] = {d.name for d in declared}

    for decl in declared:
        if decl.name in runtime_inputs and runtime_inputs[decl.name] is not None:
            try:
                resolved[decl.name] = _coerce_input(runtime_inputs[decl.name], decl.type)
            except ValueError as e:
                raise BlockExecutionError(
                    code="INVALID_INPUT",
                    message=f"input '{decl.name}' type mismatch: {e}",
                ) from None
        elif decl.default is not None:
            try:
                resolved[decl.name] = _coerce_input(decl.default, decl.type)
            except ValueError:
                resolved[decl.name] = decl.default
        elif decl.required:
            raise BlockExecutionError(
                code="MISSING_INPUT",
                message=f"required pipeline input '{decl.name}' not provided",
            )
        else:
            resolved[decl.name] = None

    # Any runtime key not declared → warn via log (silent best-effort; we don't
    # raise so ad-hoc preview calls don't break).
    for key in runtime_inputs.keys():
        if key not in known_names:
            logger.warning("Pipeline input '%s' provided but not declared — ignored", key)
    return resolved


def _resolve_params(
    params: dict[str, Any],
    resolved_inputs: dict[str, Any],
    declared_names: set[str],
    node_id: str,
) -> dict[str, Any]:
    """Replace any `"$name"` string values in params with the corresponding resolved input.

    MVP: only full-string references like `"$tool_id"`. No interpolation.
    """
    out: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, str) and v.startswith("$"):
            ref = v[1:]
            if ref not in declared_names:
                raise BlockExecutionError(
                    code="UNDECLARED_INPUT_REF",
                    message=f"node '{node_id}' param '{k}' references ${ref} but pipeline has no such input",
                )
            out[k] = resolved_inputs.get(ref)
        else:
            out[k] = v
    return out


def _topological_order(pipeline: PipelineJSON) -> list[str]:
    graph: dict[str, list[str]] = defaultdict(list)
    in_deg: dict[str, int] = defaultdict(int)
    for node in pipeline.nodes:
        in_deg.setdefault(node.id, 0)
    for edge in pipeline.edges:
        graph[edge.from_.node].append(edge.to.node)
        in_deg[edge.to.node] += 1

    queue = deque([n for n, d in in_deg.items() if d == 0])
    order: list[str] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for nxt in graph[n]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(pipeline.nodes):
        # Phase 8 debug — caller (frontend) keeps hitting this; log the
        # actual node IDs + edges so we can see whether canvas state has
        # phantom edges or duplicate IDs that the UI doesn't show.
        import logging as _lg
        _log = _lg.getLogger("python_ai_sidecar.executor.cycle")
        node_ids = [n.id for n in pipeline.nodes]
        edges_repr = [f"{e.from_.node}->{e.to.node}" for e in pipeline.edges]
        _log.error(
            "cycle detected: nodes=%s (count=%d) edges=%s order_so_far=%s",
            node_ids, len(pipeline.nodes), edges_repr, order,
        )
        raise RuntimeError("Pipeline contains a cycle — validator should have caught this")
    return order


def _build_input_map(pipeline: PipelineJSON) -> dict[str, list[tuple[str, str, str]]]:
    """node_id → [(source_node, source_port, dest_port), ...]"""
    mapping: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in pipeline.edges:
        mapping[edge.to.node].append((edge.from_.node, edge.from_.port, edge.to.port))
    return mapping


def _preview_output(outputs: dict[str, Any], sample_size: int = _PREVIEW_ROWS_DEFAULT) -> dict[str, Any]:
    """Build a preview payload for the UI.

    sample_size controls how many rows are returned for dataframe ports.
    Set high (e.g. 1000) to effectively 'return all' for small datasets.
    """
    preview: dict[str, Any] = {}
    for port, value in outputs.items():
        if isinstance(value, pd.DataFrame):
            cols = list(value.columns)[:_PREVIEW_MAX_COLS]
            head = value.head(sample_size)[cols]
            preview[port] = {
                "type": "dataframe",
                "columns": cols,
                "rows": head.astype(object).where(head.notna(), None).to_dict(orient="records"),
                "total": int(len(value)),
            }
        elif isinstance(value, bool):  # must precede int check (bool is subclass of int)
            preview[port] = {"type": "bool", "value": value}
        elif isinstance(value, dict):
            preview[port] = {"type": "dict", "snapshot": value}
        elif isinstance(value, list):
            preview[port] = {"type": "list", "length": len(value), "sample": value[:5]}
        else:
            preview[port] = {"type": type(value).__name__, "value": value}
    return preview


def _rows_count(outputs: dict[str, Any]) -> Optional[int]:
    for v in outputs.values():
        if isinstance(v, pd.DataFrame):
            return int(len(v))
        if isinstance(v, dict) and "count" in v:
            try:
                return int(v["count"])
            except (TypeError, ValueError):
                return None
    return None


def _pick_terminal_logic_node(
    pipeline: PipelineJSON,
    cache: "RunCache",
) -> Optional[str]:
    """Identify the terminal Logic Node.

    A Logic Node exposes output port 'triggered'. "Terminal" means no
    downstream node consumes its 'triggered' port — i.e. it represents the
    pipeline's final trigger decision.

    Returns node_id of the terminal logic node, or None if the pipeline has
    no logic node.
    """
    # Nodes whose cache has a 'triggered' output and whose value is a bool.
    logic_candidates: set[str] = set()
    for node in pipeline.nodes:
        outputs = cache.get(node.id)
        if outputs is None:
            continue
        if "triggered" in outputs and isinstance(outputs["triggered"], bool):
            logic_candidates.add(node.id)

    if not logic_candidates:
        return None

    # Drop any whose 'triggered' port is consumed by a downstream edge.
    consumed = {
        edge.from_.node
        for edge in pipeline.edges
        if edge.from_.node in logic_candidates and edge.from_.port == "triggered"
    }
    terminals = logic_candidates - consumed

    # Deterministic pick when there are multiple (rare): last in topo order.
    if not terminals:
        # All logic nodes feed downstream (unusual) — fall back to the one
        # whose graph depth is deepest.
        terminals = logic_candidates

    order = _topological_order(pipeline)
    order_rank = {nid: i for i, nid in enumerate(order)}
    return max(terminals, key=lambda nid: order_rank.get(nid, -1))


def _collect_chart_summaries(
    pipeline: PipelineJSON,
    cache: "RunCache",
) -> list[dict[str, Any]]:
    """Gather all chart nodes in pipeline, sorted by 'sequence' param (fallback: position.x).

    Returns [{ node_id, sequence, title?, chart_spec }] ordered for display.
    """
    charts: list[tuple[int, float, dict[str, Any]]] = []
    for node in pipeline.nodes:
        if node.block_id != "block_chart":
            continue
        outputs = cache.get(node.id)
        if outputs is None:
            continue
        spec = outputs.get("chart_spec")
        if spec is None:
            continue
        seq_raw = (node.params or {}).get("sequence")
        seq = int(seq_raw) if isinstance(seq_raw, int) else 10_000  # unsequenced → end
        # Stable tie-break: position.x (left → right on canvas)
        px = float(node.position.x) if node.position else 0.0
        entry = {
            "node_id": node.id,
            "sequence": seq if isinstance(seq_raw, int) else None,
            "title": (node.params or {}).get("title") or node.display_label or node.id,
            "chart_spec": spec,
        }
        charts.append((seq, px, entry))
    charts.sort(key=lambda t: (t[0], t[1]))
    return [c[2] for c in charts]


def _collect_data_view_summaries(
    pipeline: PipelineJSON,
    cache: "RunCache",
) -> list[dict[str, Any]]:
    """PR-E1: Gather all block_data_view nodes; ordered by sequence param then position.x.

    Each entry: { node_id, sequence, title, description?, columns, rows, total_rows }
    """
    views: list[tuple[int, float, dict[str, Any]]] = []
    for node in pipeline.nodes:
        if node.block_id != "block_data_view":
            continue
        outputs = cache.get(node.id)
        if outputs is None:
            continue
        spec = outputs.get("data_view")
        if not isinstance(spec, dict):
            continue
        seq_raw = (node.params or {}).get("sequence")
        seq = int(seq_raw) if isinstance(seq_raw, int) else 10_000
        px = float(node.position.x) if node.position else 0.0
        entry = {
            "node_id": node.id,
            "sequence": seq if isinstance(seq_raw, int) else None,
            "title": spec.get("title") or node.display_label or node.id,
            "description": spec.get("description"),
            "columns": spec.get("columns") or [],
            "rows": spec.get("rows") or [],
            "total_rows": spec.get("total_rows", 0),
        }
        views.append((seq, px, entry))
    views.sort(key=lambda t: (t[0], t[1]))
    return [v[2] for v in views]


def _build_result_summary(
    pipeline: PipelineJSON,
    cache: "RunCache",
) -> Optional[dict[str, Any]]:
    """Compute pipeline-level triggered/evidence (terminal logic node) + chart list.

    Returns None only when the pipeline has neither a logic node nor a chart node.
    """
    terminal_id = _pick_terminal_logic_node(pipeline, cache)
    charts = _collect_chart_summaries(pipeline, cache)
    data_views = _collect_data_view_summaries(pipeline, cache)
    if terminal_id is None and not charts and not data_views:
        return None

    if terminal_id is not None:
        outputs = cache.get(terminal_id) or {}
        triggered = bool(outputs.get("triggered", False))
        evidence = outputs.get("evidence")
        evidence_rows = int(len(evidence)) if isinstance(evidence, pd.DataFrame) else 0
    else:
        triggered = False
        evidence_rows = 0

    return {
        "triggered": triggered,
        "evidence_node_id": terminal_id,
        "evidence_rows": evidence_rows,
        "charts": charts,
        "data_views": data_views,
    }


class PipelineExecutor:
    """Execute a Pipeline JSON against a loaded BlockRegistry."""

    def __init__(self, registry: BlockRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        pipeline: PipelineJSON,
        *,
        run_id: Optional[int] = None,
        preview_sample_size: int = _PREVIEW_ROWS_DEFAULT,
        inputs: Optional[dict[str, Any]] = None,
        on_event: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Run the pipeline end-to-end.

        Phase 5-UX-5: when `on_event` is provided (a callable taking a dict),
        per-node lifecycle events are emitted so upper layers can stream them
        (e.g. SSE to the chat UI for progressive DAG animation).
        Event shapes:
          {"type": "pb_run_start", "run_id": int|None, "node_count": int, "order": [node_id,...]}
          {"type": "pb_node_start", "node_id": str, "block_id": str, "sequence": int}
          {"type": "pb_node_done",  "node_id": str, "status": "success"|"failed"|"skipped",
                                    "rows": int|None, "duration_ms": float, "error": str|None}
          {"type": "pb_run_done", "run_id": int|None, "status": str, "duration_ms": float}
        Event callback is fire-and-forget; exceptions inside are swallowed.
        """
        def _emit(event: dict[str, Any]) -> None:
            if on_event is None:
                return
            try:
                on_event(event)
            except Exception as e:  # noqa: BLE001
                logger.debug("on_event callback failed: %s", e)

        started = time.perf_counter()
        started_at = datetime.now(tz=timezone.utc).isoformat()
        cache = RunCache(run_id=run_id)
        ctx = ExecutionContext(run_id=run_id)

        node_results: dict[str, dict[str, Any]] = {}
        error_message: Optional[str] = None
        overall_status = "success"

        # Phase 4-B0: resolve pipeline inputs once up-front.
        try:
            resolved_inputs = _resolve_inputs(pipeline, inputs or {})
        except BlockExecutionError as e:
            return {
                "status": "failed",
                "node_results": {},
                "error_message": f"Input resolution failed: [{e.code}] {e.message}",
                "duration_ms": 0.0,
                "started_at": started_at,
                "finished_at": datetime.now(tz=timezone.utc).isoformat(),
                "result_summary": None,
            }
        declared_names = {d.name for d in (pipeline.inputs or [])}

        try:
            order = _topological_order(pipeline)
        except RuntimeError as e:
            return {
                "status": "failed",
                "node_results": {},
                "error_message": str(e),
                "duration_ms": 0.0,
                "started_at": started_at,
                "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        inbound = _build_input_map(pipeline)
        node_by_id = {n.id: n for n in pipeline.nodes}

        _emit({
            "type": "pb_run_start",
            "run_id": run_id,
            "node_count": len(order),
            "order": list(order),
        })

        for seq_idx, node_id in enumerate(order):
            node = node_by_id[node_id]
            _emit({
                "type": "pb_node_start",
                "node_id": node_id,
                "block_id": node.block_id,
                "sequence": seq_idx,
            })
            # gather inputs from upstream outputs
            inputs: dict[str, Any] = {}
            skip_reason: Optional[str] = None
            for src_node, src_port, dest_port in inbound.get(node_id, []):
                if not cache.has(src_node):
                    skip_reason = f"upstream node '{src_node}' failed or skipped"
                    break
                upstream_outputs = cache.get(src_node) or {}
                if src_port not in upstream_outputs:
                    skip_reason = f"upstream port '{src_node}.{src_port}' missing"
                    break
                inputs[dest_port] = upstream_outputs[src_port]

            if skip_reason:
                node_results[node_id] = {
                    "status": "skipped",
                    "error": skip_reason,
                    "rows": None,
                    "duration_ms": 0.0,
                    "preview": None,
                }
                overall_status = "failed"
                _emit({
                    "type": "pb_node_done", "node_id": node_id,
                    "status": "skipped", "rows": None, "duration_ms": 0.0,
                    "error": skip_reason,
                })
                continue

            executor = self.registry.get_executor(node.block_id, node.block_version)
            if executor is None:
                err = f"No executor registered for {node.block_id}@{node.block_version}"
                node_results[node_id] = {
                    "status": "failed",
                    "error": err,
                    "rows": None,
                    "duration_ms": 0.0,
                    "preview": None,
                }
                overall_status = "failed"
                _emit({
                    "type": "pb_node_done", "node_id": node_id,
                    "status": "failed", "rows": None, "duration_ms": 0.0,
                    "error": err,
                })
                continue

            # Resolve pipeline-level input refs ($name) before calling the block.
            try:
                resolved_params = _resolve_params(
                    node.params or {}, resolved_inputs, declared_names, node.id
                )
            except BlockExecutionError as e:
                node_results[node_id] = {
                    "status": "failed",
                    "error": e.message,
                    "error_code": e.code,
                    "hint": e.hint,
                    "rows": None,
                    "duration_ms": 0.0,
                    "preview": None,
                }
                overall_status = "failed"
                error_message = error_message or f"{node_id}: {e.message}"
                continue

            node_started = time.perf_counter()
            try:
                outputs = await executor.execute(
                    params=resolved_params, inputs=inputs, context=ctx
                )
            except BlockExecutionError as e:
                dur = (time.perf_counter() - node_started) * 1000.0
                node_results[node_id] = {
                    "status": "failed",
                    "error": e.message,
                    "error_code": e.code,
                    "hint": e.hint,
                    "rows": None,
                    "duration_ms": dur,
                    "preview": None,
                }
                overall_status = "failed"
                error_message = error_message or f"{node_id}: {e.message}"
                logger.warning("Node %s failed: [%s] %s", node_id, e.code, e.message)
                _emit({
                    "type": "pb_node_done", "node_id": node_id,
                    "status": "failed", "rows": None, "duration_ms": dur,
                    "error": e.message,
                })
                continue
            except Exception as e:  # noqa: BLE001 — we do want to catch unexpected
                dur = (time.perf_counter() - node_started) * 1000.0
                node_results[node_id] = {
                    "status": "failed",
                    "error": f"{type(e).__name__}: {e}",
                    "rows": None,
                    "duration_ms": dur,
                    "preview": None,
                }
                overall_status = "failed"
                error_message = error_message or f"{node_id}: {type(e).__name__}: {e}"
                logger.exception("Node %s raised unexpected error", node_id)
                _emit({
                    "type": "pb_node_done", "node_id": node_id,
                    "status": "failed", "rows": None, "duration_ms": dur,
                    "error": f"{type(e).__name__}: {e}",
                })
                continue

            cache.set(node_id, outputs)
            dur = (time.perf_counter() - node_started) * 1000.0
            rows = _rows_count(outputs)
            node_results[node_id] = {
                "status": "success",
                "error": None,
                "rows": rows,
                "duration_ms": dur,
                "preview": _preview_output(outputs, sample_size=preview_sample_size),
            }
            _emit({
                "type": "pb_node_done", "node_id": node_id,
                "status": "success", "rows": rows, "duration_ms": dur,
                "error": None,
            })

        duration_ms = (time.perf_counter() - started) * 1000.0
        result_summary = _build_result_summary(pipeline, cache)
        _emit({
            "type": "pb_run_done",
            "run_id": run_id,
            "status": overall_status,
            "duration_ms": duration_ms,
        })
        result = {
            "status": overall_status,
            "node_results": node_results,
            "error_message": error_message,
            "duration_ms": duration_ms,
            "started_at": started_at,
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "result_summary": result_summary,
        }
        cache.dispose()
        return result
