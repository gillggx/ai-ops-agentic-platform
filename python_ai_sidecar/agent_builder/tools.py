"""BuilderToolset — 14 tools the Glass Box Agent calls to build a pipeline.

Each tool is an async method that:
  1. Mutates `session.pipeline_json` (for canvas ops) OR reads state / runs preview
  2. Records an Operation in session.operations with timing
  3. Returns a JSON-serializable dict (the tool result shown to the LLM)

Tool failures raise `ToolError` with a structured message. The orchestrator
converts these to `tool_result.is_error = True` so the LLM can read the message
and retry (bounded).

CLAUDE.md compliance:
  - list_blocks() reads BlockRegistry (DB) — no hardcoded catalog
  - Each param/port comes from block.param_schema / input_schema / output_schema
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON, PipelineNode, PipelineEdge, EdgeEndpoint, NodePosition
from python_ai_sidecar.agent_builder.session import (
    AgentBuilderSession,
    ChatMsg,
    ErrorEvent,
    Operation,
)
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
from python_ai_sidecar.pipeline_builder.executor import PipelineExecutor
from python_ai_sidecar.pipeline_builder.validator import PipelineValidator


class ToolError(Exception):
    """Raised by a tool when execution fails; visible to the Agent LLM."""

    def __init__(self, code: str, message: str, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"error": True, "code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


class ToolGateError(ToolError):
    """Gate condition failed (e.g. finish without validate). Not a bug — Agent retries."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NODE_OFFSET_STEP = 30
_NODE_OFFSET_TOLERANCE = 20


def _smart_offset(existing: list[PipelineNode], desired: dict[str, float]) -> NodePosition:
    """Match frontend's reducer smart-offset for consistency."""
    pos = {"x": float(desired.get("x", 0.0)), "y": float(desired.get("y", 0.0))}
    for _ in range(40):
        clash = any(
            abs(n.position.x - pos["x"]) < _NODE_OFFSET_TOLERANCE
            and abs(n.position.y - pos["y"]) < _NODE_OFFSET_TOLERANCE
            for n in existing
        )
        if not clash:
            break
        pos["x"] += _NODE_OFFSET_STEP
        pos["y"] += _NODE_OFFSET_STEP
    return NodePosition(x=pos["x"], y=pos["y"])


def _gen_node_id(nodes: list[PipelineNode]) -> str:
    existing = {n.id for n in nodes}
    i = 1
    while f"n{i}" in existing:
        i += 1
    return f"n{i}"


def _gen_edge_id(edges: list[PipelineEdge]) -> str:
    existing = {e.id for e in edges}
    i = 1
    while f"e{i}" in existing:
        i += 1
    return f"e{i}"


def _ports(spec: Optional[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return (spec or {}).get(key) or []


def _port_type(spec: Optional[dict[str, Any]], port: str, kind: str) -> Optional[str]:
    ports = _ports(spec, f"{kind}_schema")
    for p in ports:
        if p.get("port") == port:
            return p.get("type")
    return None


# 2026-05-04: column-ref validation. Many transform/output blocks reference
# upstream column names (sort.column, filter.column, chart.x, data_view.columns
# etc.). The most common Glass Box failure is the LLM picking a column name
# that doesn't actually exist in the upstream — e.g. `sort.column='count'`
# when upstream is `groupby_agg(agg_column='spc_status', agg_func='count')`
# whose actual output column is `spc_status_count`. Auto-run fails on the
# downstream block. This helper computes the expected column set for a node's
# upstream so set_param can reject obvious mistakes at write time.

# Keys whose value should reference an upstream column. List values
# (block_data_view.columns, block_sort.columns) get each element checked.
COLUMN_REF_KEYS: frozenset = frozenset({
    "column", "agg_column", "group_by",
    "x", "y",
    "ucl_column", "lcl_column", "highlight_column",
    "columns",
    "x_column", "y_column",
    "category_column", "value_column",
    "sort_column",
})


def _find_upstream_node(pipeline: PipelineJSON, node_id: str) -> Optional[PipelineNode]:
    """Return the FIRST upstream node feeding `node_id` via any data edge.
    Caller usually only cares about the dataframe upstream — chained transforms
    have one inbound data edge."""
    edge_info = _find_upstream_edge(pipeline, node_id)
    return edge_info[0] if edge_info else None


def _find_upstream_edge(
    pipeline: PipelineJSON, node_id: str
) -> Optional[tuple[PipelineNode, str]]:
    """Return (upstream_node, from_port) for the first edge feeding node_id.
    Port info matters for multi-port blocks like block_linear_regression
    where stats/data/ci ports emit completely different schemas."""
    for edge in pipeline.edges:
        if edge.to.node == node_id:
            for n in pipeline.nodes:
                if n.id == edge.from_.node:
                    return n, edge.from_.port
    return None


def _columns_for_block_port(
    pipeline: PipelineJSON,
    upstream: PipelineNode,
    registry: BlockRegistry,
    from_port: str,
    *,
    depth: int = 0,
) -> Optional[list[str]]:
    """Schema for `upstream`'s output on a specific port. Multi-port blocks
    (linear_regression with stats/data/ci) need this; single-port blocks
    ignore the port arg."""
    if depth > 5:
        return None
    spec = registry.get_spec(upstream.block_id, upstream.block_version)
    if spec is None:
        return None
    block_id = upstream.block_id
    params = upstream.params or {}

    # ── Multi-port blocks ────────────────────────────────────────────────
    if block_id == "block_linear_regression":
        if from_port == "data":
            # Pass-through: LR `data` port preserves upstream cols + adds
            # <y_column>_pred / <y_column>_residual / group. To validate
            # something like x="eventTime" downstream, recurse to find the
            # LR's own upstream cols.
            inner = _expected_upstream_columns(pipeline, upstream, registry, depth=depth + 1) or []
            y = params.get("y_column")
            extras = [f"{y}_pred", f"{y}_residual", "group"] if y else ["group"]
            return list(inner) + extras
        if from_port == "ci":
            x_col = params.get("x_column", "x")
            return [x_col, "pred", "ci_lower", "ci_upper", "group"]
        # Default / "stats" port
        return ["slope", "intercept", "r_squared", "p_value", "n", "stderr", "group"]

    # ── Dynamic-output blocks: column names depend on params ─────────────
    # block_process_history.nested controls the shape of its output. Static
    # output_columns_hint only lists the FLAT mode columns; when the user
    # opts into nested (default since 2026-05-13) we surface path entries the
    # LLM can actually use (spc_summary.ooc_count / spc_charts[].name etc.).
    if block_id == "block_process_history":
        nested = params.get("nested")
        if nested is None:
            nested = True  # current default
        if nested:
            # Base scalar fields + spc_summary + spc_charts array + nested
            # APC / DC / RECIPE / FDC / EC sub-objects. Use array-syntax for
            # spc_charts items so LLM knows it's an array path.
            return [
                "eventTime", "toolID", "lotID", "step",
                "spc_status", "fdc_classification",
                # spc_summary precomputed
                "spc_summary.ooc_count",
                "spc_summary.total_charts",
                "spc_summary.ooc_chart_names",
                # spc_charts array path
                "spc_charts",
                "spc_charts[].name",
                "spc_charts[].value",
                "spc_charts[].ucl",
                "spc_charts[].lcl",
                "spc_charts[].is_ooc",
                "spc_charts[].status",
                # APC / DC / RECIPE / FDC / EC stay as nested object subtrees
                "APC", "APC.objectID", "APC.parameters",
                "DC", "DC.chamberID",
                "RECIPE", "RECIPE.objectID", "RECIPE.recipe_version",
                "FDC", "FDC.classification", "FDC.fault_code",
                "EC", "EC.constants",
            ]
        # Fall through to flat-hint walk below for nested=False
    if block_id == "block_unnest":
        # Output columns = elements of the upstream array, lifted to top-level.
        # We don't statically know what's inside an arbitrary array, but for the
        # common `spc_charts` array (the SPC use case) we can hardcode the schema
        # because it comes from block_process_history(nested=true).
        column = (params.get("column") or "").strip()
        if column in ("spc_charts", "spc_charts[]"):
            up_cols = _expected_upstream_columns(pipeline, upstream, registry, depth=depth + 1) or []
            # Keep sibling top-level cols + add per-element fields
            keep = [c for c in up_cols if not c.startswith("spc_charts") and not c.startswith("spc_summary")]
            return keep + ["name", "value", "ucl", "lcl", "is_ooc", "status"]
        # Generic case — assume sibling columns + can't introspect inside array
        return _expected_upstream_columns(pipeline, upstream, registry, depth=depth + 1)
    if block_id == "block_pluck":
        path = (params.get("path") or "").strip()
        as_col = (params.get("as_column") or "").strip()
        if not path:
            return None
        out_col = as_col or path.rsplit(".", 1)[-1].replace("[]", "")
        if params.get("keep_other"):
            up = _expected_upstream_columns(pipeline, upstream, registry, depth=depth + 1) or []
            return list(up) + [out_col]
        return [out_col]
    if block_id == "block_select":
        fields = params.get("fields") or []
        if not isinstance(fields, list):
            return None
        out: list[str] = []
        for f in fields:
            if not isinstance(f, dict):
                continue
            p = f.get("path") or ""
            name = f.get("as") or p.rsplit(".", 1)[-1].replace("[]", "")
            if name:
                out.append(name)
        return out or None

    if block_id == "block_groupby_agg":
        cols: list[str] = []
        group_by = (params.get("group_by") or "").strip()
        if group_by:
            cols.extend([g.strip() for g in group_by.split(",") if g.strip()])
        agg_col = params.get("agg_column")
        agg_fn = params.get("agg_func")
        if agg_col and agg_fn:
            cols.append(f"{agg_col}_{agg_fn}")
        return cols or None

    if block_id == "block_count_rows":
        return ["count"]

    if block_id == "block_cpk":
        return ["cpk", "cpu", "cpl", "mean", "std", "lsl", "usl", "n"]

    if block_id == "block_hypothesis_test":
        return ["test", "statistic", "p_value", "significant", "n"]

    if block_id == "block_correlation":
        return ["x_column", "y_column", "pearson_r", "spearman_r", "n"]

    # Pass-through blocks: same columns as their upstream
    if block_id in ("block_filter", "block_sort", "block_delta", "block_threshold"):
        return _expected_upstream_columns(pipeline, upstream, registry, depth=depth + 1)

    # Static-hint blocks (sources): use output_columns_hint from registry.
    # 2026-05-13 (Phase 1 object-native): walk the hint as JSON-Schema-ish
    # and return PATH list (top-level names for flat blocks, but a.b /
    # a[].b for nested ones). Existing flat blocks still get flat path
    # strings — they happen to coincide with top-level names — so callers
    # see no shape change unless the block declared nested fields.
    hint = spec.get("output_columns_hint") or []
    if isinstance(hint, list) and hint:
        try:
            from python_ai_sidecar.pipeline_builder.path import walk_paths
            paths = walk_paths(hint)
            if paths:
                return paths
        except Exception:  # noqa: BLE001
            pass
        # Fallback: legacy shape (list of dict/str with name only) — flat keys.
        cols2 = []
        for c in hint:
            if isinstance(c, dict) and c.get("name"):
                cols2.append(c["name"])
            elif isinstance(c, str):
                cols2.append(c)
        return cols2 or None

    return None


def _expected_upstream_columns(
    pipeline: PipelineJSON,
    node: PipelineNode,
    registry: BlockRegistry,
    *,
    depth: int = 0,
) -> Optional[list[str]]:
    """Compute the columns node's upstream is expected to emit on the
    actual connecting port. Recurses through pass-through blocks up to
    5 levels."""
    if depth > 5:
        return None
    edge_info = _find_upstream_edge(pipeline, node.id)
    if edge_info is None:
        return None
    upstream, from_port = edge_info
    return _columns_for_block_port(pipeline, upstream, registry, from_port, depth=depth)


_TEMPLATE_TOKEN_RE = re.compile(r"<[^>]+>")


def _column_matches_expected(candidate: str, expected: list[str]) -> bool:
    """True if candidate equals a literal entry OR matches a template
    entry like 'apc_<param_name>' (treated as regex 'apc_.+'). Source
    blocks emit dynamic columns (APC params, DC sensors, recipe params,
    EC constants) whose hint entries are templated; without this,
    legitimate column refs like 'apc_etch_time_offset' fail the literal
    set membership check."""
    for entry in expected:
        if entry == candidate:
            return True
        if "<" in entry and ">" in entry:
            pattern = _TEMPLATE_TOKEN_RE.sub(".+", re.escape(entry).replace(r"\<", "<").replace(r"\>", ">"))
            if re.fullmatch(pattern, candidate):
                return True
    return False


def _alternative_port_match(
    pipeline: PipelineJSON,
    upstream: PipelineNode,
    registry: BlockRegistry,
    current_port: str,
    requested_columns: list[str],
) -> Optional[tuple[str, list[str]]]:
    """If a non-current port of `upstream` would actually contain
    `requested_columns`, return (better_port_name, that_port_columns).
    Used to nudge the LLM toward switching ports instead of giving up."""
    spec = registry.get_spec(upstream.block_id, upstream.block_version)
    if not spec:
        return None
    output_ports = _ports(spec, "output_schema")
    if len(output_ports) <= 1:
        return None
    for port in output_ports:
        port_name = port.get("port")
        if not port_name or port_name == current_port:
            continue
        cols = _columns_for_block_port(pipeline, upstream, registry, port_name)
        if cols and all(_column_matches_expected(c, cols) for c in requested_columns):
            return port_name, cols
    return None


def _check_column_in_upstream(
    pipeline: PipelineJSON,
    node: PipelineNode,
    registry: BlockRegistry,
    *,
    param_key: str,
    value: Any,
) -> None:
    """Raise ToolError when value references a column the upstream won't
    emit. No-op when upstream schema is unknown (LLM is expected to
    run_preview first per the system-prompt 'Column reference rule')."""
    if param_key not in COLUMN_REF_KEYS:
        return

    # Collect candidate column-name strings to check
    candidates: list[str] = []
    if isinstance(value, str):
        # Skip placeholder refs — those are validated separately
        if value.startswith("$"):
            return
        candidates = [value]
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, str) and not v.startswith("$"):
                candidates.append(v)
            elif isinstance(v, dict):
                # block_sort columns: [{column, order}]
                col = v.get("column")
                if isinstance(col, str) and not col.startswith("$"):
                    candidates.append(col)
    if not candidates:
        return

    expected = _expected_upstream_columns(pipeline, node, registry)
    if expected is None:
        return  # unknown — let LLM proceed; runtime executor catches

    bad = [c for c in candidates if not _column_matches_expected(c, expected)]
    if not bad:
        return
    expected_set = set(expected)

    edge_info = _find_upstream_edge(pipeline, node.id)
    upstream = edge_info[0] if edge_info else None
    current_port = edge_info[1] if edge_info else "?"
    upstream_label = (upstream.block_id if upstream else "?")

    # If a sibling port on the same upstream actually has the requested
    # columns, surface that — saves the LLM from a multi-turn guess loop
    # (the linear_regression stats vs data vs ci confusion).
    port_hint = ""
    if upstream is not None:
        alt = _alternative_port_match(pipeline, upstream, registry, current_port, bad)
        if alt is not None:
            alt_port, alt_cols = alt
            port_hint = (
                f"⚠ The columns {bad!r} ARE available on '{upstream_label}'s "
                f"`{alt_port}` port (outputs {sorted(alt_cols)}). You connected "
                f"to the `{current_port}` port — disconnect and reconnect using "
                f"`{alt_port}` instead. "
            )

    raise ToolError(
        code="COLUMN_NOT_IN_UPSTREAM",
        message=(
            f"node '{node.id}' param '{param_key}' references column(s) "
            f"{bad!r} but upstream '{upstream_label}' (port `{current_port}`) "
            f"outputs {sorted(expected_set)}."
        ),
        hint=(
            port_hint
            + f"Use one of {sorted(expected_set)}. "
            "Or call run_preview on the upstream node to confirm column names. "
            "For groupby_agg upstream, the aggregated column is named "
            "`<agg_column>_<agg_func>` (e.g. `spc_status_count`), not just "
            "the agg_func name."
        ),
    )


def _check_placeholder_declared(
    pipeline: PipelineJSON,
    value: Any,
    *,
    param_key: str,
    node_id: Optional[str] = None,
) -> None:
    """Reject `$xxx` values that don't reference a declared pipeline input.

    Left-shifts validator rule C10 from finish() to write-time so a bad
    placeholder never reaches the canvas via SSE op events. Raised early,
    the LLM sees the error in its tool-use loop and can fix in-place.

    Only checks `$xxx` strings. Literals (e.g. "EQP-01") pass through.
    """
    if not isinstance(value, str) or not value.startswith("$"):
        return
    ref = value[1:]
    declared = {inp.name for inp in (pipeline.inputs or [])}
    if ref in declared:
        return
    where = f"node '{node_id}' " if node_id else ""
    declared_list = ", ".join(f"${n}" for n in sorted(declared)) or "(none)"
    raise ToolError(
        code="UNDECLARED_INPUT_REF",
        message=(
            f"{where}param '{param_key}' references {value} "
            f"but pipeline.inputs has no '{ref}' declared. "
            f"Currently declared inputs: {declared_list}."
        ),
        hint=(
            "Fix one of these ways: "
            f"(a) write a literal value (e.g. \"EQP-01\") instead of {value}; "
            f"(b) call declare_input(name='{ref}', example=...) first, then "
            f"reference {value}; "
            "(c) reuse the canonical name $tool_id (already declared in most "
            "patrol-ready pipelines) instead of inventing a new one."
        ),
    )


# ---------------------------------------------------------------------------
# BuilderToolset
# ---------------------------------------------------------------------------


class BuilderToolset:
    """14 tools that the Agent calls to build/inspect a pipeline."""

    def __init__(
        self,
        session: AgentBuilderSession,
        registry: BlockRegistry,
    ) -> None:
        self.session = session
        self.registry = registry
        self.executor = PipelineExecutor(registry)

    # ----------------------------------------------------------------------
    # Dispatch
    # ----------------------------------------------------------------------

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a named tool call and record it. Returns tool result dict."""
        fn = getattr(self, name, None)
        if fn is None or not callable(fn):
            raise ToolError(code="UNKNOWN_TOOL", message=f"No tool named '{name}'")
        start = time.perf_counter()
        try:
            result = await fn(**args)
            elapsed = (time.perf_counter() - start) * 1000.0
            self.session.record_op(Operation(op=name, args=args, result=result, elapsed_ms=elapsed))
            return result
        except ToolError as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            err = ErrorEvent(op=name, message=e.message, hint=e.hint)
            self.session.record_error(err)
            self.session.record_op(
                Operation(op=name, args=args, result=e.to_dict(), elapsed_ms=elapsed)
            )
            raise
        except Exception as e:  # noqa: BLE001
            elapsed = (time.perf_counter() - start) * 1000.0
            msg = f"{type(e).__name__}: {e}"
            err = ErrorEvent(op=name, message=msg)
            self.session.record_error(err)
            self.session.record_op(
                Operation(op=name, args=args, result={"error": True, "message": msg}, elapsed_ms=elapsed)
            )
            raise ToolError(code="INTERNAL_ERROR", message=msg) from e

    # ======================================================================
    # Canvas operations (8)
    # ======================================================================

    async def list_blocks(self, category: Optional[str] = None) -> dict[str, Any]:
        """Return block catalog from DB (filtered by category if given)."""
        catalog = self.registry.catalog
        items = []
        # 2026-05-04 cost cut: list_blocks now returns 1-line summary per
        # block instead of the full description / param_schema / examples
        # blob. Saved ~15K tokens per tool result. Caller must use
        # explain_block() to fetch the full spec for blocks they want to
        # add to the canvas.
        for (name, version), spec in catalog.items():
            if category and spec.get("category") != category:
                continue
            desc = (spec.get("description") or "").strip()
            head = desc.split("\n", 1)[0].strip() if desc else ""
            if len(head) > 100:
                head = head[:100].rsplit(" ", 1)[0] + "…"
            items.append({
                "name": name,
                "version": version,
                "category": spec.get("category"),
                "status": spec.get("status"),
                "summary": head,
            })
        return {
            "blocks": items,
            "count": len(items),
            "hint": "Call explain_block(block_name) for full param_schema + examples before adding to canvas.",
        }

    async def explain_block(
        self,
        block_name: str,
        block_version: str = "1.0.0",
    ) -> dict[str, Any]:
        """Return full spec for one block: description, ports, param_schema,
        examples. Companion to the slim list_blocks index — use before
        add_node so the LLM picks correct params on the first try.
        """
        spec = self.registry.get_spec(block_name, block_version)
        if spec is None:
            raise ToolError(
                code="BLOCK_NOT_FOUND",
                message=f"Block '{block_name}@{block_version}' not in catalog",
                hint="Browse list_blocks() for available names.",
            )
        return {
            "name": block_name,
            "version": block_version,
            "category": spec.get("category"),
            "status": spec.get("status"),
            "description": spec.get("description"),
            "input_schema": spec.get("input_schema") or [],
            "output_schema": spec.get("output_schema") or [],
            "param_schema": spec.get("param_schema") or {},
            "examples": spec.get("examples") or [],
        }

    async def add_node(
        self,
        block_name: str,
        block_version: str = "1.0.0",
        position: Optional[dict[str, float]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Add a node to the canvas. Auto-offsets if position collides."""
        spec = self.registry.get_spec(block_name, block_version)
        if spec is None:
            raise ToolError(
                code="BLOCK_NOT_FOUND",
                message=f"Block '{block_name}@{block_version}' not in catalog",
                hint="Call list_blocks() to see available blocks.",
            )
        pipeline = self.session.pipeline_json
        # Reject `$xxx` placeholders that don't match a declared input before
        # the node hits canvas via SSE — see _check_placeholder_declared.
        for k, v in (params or {}).items():
            _check_placeholder_declared(pipeline, v, param_key=k)
        # Column-ref check is deferred to set_param time; add_node is usually
        # called before the upstream edge exists (so we can't validate yet).
        # If params include column refs at add_node time, they'll be re-checked
        # the next time set_param touches them.
        desired = position or {"x": 40.0 + 200.0 * len(pipeline.nodes), "y": 80.0}
        final_pos = _smart_offset(pipeline.nodes, desired)
        node_id = _gen_node_id(pipeline.nodes)
        new_node = PipelineNode(
            id=node_id,
            block_id=block_name,
            block_version=block_version,
            position=final_pos,
            params=params or {},
        )
        pipeline.nodes.append(new_node)
        return {"node_id": node_id, "position": {"x": final_pos.x, "y": final_pos.y}}

    async def remove_node(self, node_id: str) -> dict[str, Any]:
        pipeline = self.session.pipeline_json
        before_n = len(pipeline.nodes)
        pipeline.nodes = [n for n in pipeline.nodes if n.id != node_id]
        if len(pipeline.nodes) == before_n:
            raise ToolError(code="NODE_NOT_FOUND", message=f"Node '{node_id}' not in pipeline")
        removed_edges = [e.id for e in pipeline.edges if e.from_.node == node_id or e.to.node == node_id]
        pipeline.edges = [
            e for e in pipeline.edges if e.from_.node != node_id and e.to.node != node_id
        ]
        return {"removed_node": node_id, "removed_edges": removed_edges}

    async def connect(
        self, from_node: str, from_port: str, to_node: str, to_port: str
    ) -> dict[str, Any]:
        pipeline = self.session.pipeline_json
        src = next((n for n in pipeline.nodes if n.id == from_node), None)
        dst = next((n for n in pipeline.nodes if n.id == to_node), None)
        if src is None:
            raise ToolError(code="NODE_NOT_FOUND", message=f"from_node '{from_node}' not in pipeline")
        if dst is None:
            raise ToolError(code="NODE_NOT_FOUND", message=f"to_node '{to_node}' not in pipeline")

        src_spec = self.registry.get_spec(src.block_id, src.block_version)
        dst_spec = self.registry.get_spec(dst.block_id, dst.block_version)
        src_type = _port_type(src_spec, from_port, "output")
        dst_type = _port_type(dst_spec, to_port, "input")
        if src_type is None:
            raise ToolError(
                code="PORT_NOT_FOUND",
                message=f"'{from_node}' has no output port '{from_port}'",
                hint=f"Available output ports: {[p.get('port') for p in _ports(src_spec, 'output_schema')]}",
            )
        if dst_type is None:
            raise ToolError(
                code="PORT_NOT_FOUND",
                message=f"'{to_node}' has no input port '{to_port}'",
                hint=f"Available input ports: {[p.get('port') for p in _ports(dst_spec, 'input_schema')]}",
            )
        if src_type != dst_type:
            raise ToolError(
                code="PORT_TYPE_MISMATCH",
                message=f"Port type mismatch: '{src_type}' → '{dst_type}'",
                hint=f"Connect compatible types (e.g. dataframe → dataframe).",
            )

        dup = next(
            (
                e for e in pipeline.edges
                if e.from_.node == from_node and e.from_.port == from_port
                and e.to.node == to_node and e.to.port == to_port
            ),
            None,
        )
        if dup is not None:
            return {"edge_id": dup.id, "note": "already exists"}

        edge_id = _gen_edge_id(pipeline.edges)
        edge = PipelineEdge(
            id=edge_id,
            **{"from": EdgeEndpoint(node=from_node, port=from_port)},
            to=EdgeEndpoint(node=to_node, port=to_port),
        )
        pipeline.edges.append(edge)
        return {"edge_id": edge_id}

    async def disconnect(self, edge_id: str) -> dict[str, Any]:
        pipeline = self.session.pipeline_json
        before = len(pipeline.edges)
        pipeline.edges = [e for e in pipeline.edges if e.id != edge_id]
        if len(pipeline.edges) == before:
            raise ToolError(code="EDGE_NOT_FOUND", message=f"Edge '{edge_id}' not in pipeline")
        return {"removed_edge": edge_id}

    async def set_param(self, node_id: str, key: str, value: Any) -> dict[str, Any]:
        pipeline = self.session.pipeline_json
        node = next((n for n in pipeline.nodes if n.id == node_id), None)
        if node is None:
            raise ToolError(code="NODE_NOT_FOUND", message=f"Node '{node_id}' not in pipeline")
        spec = self.registry.get_spec(node.block_id, node.block_version)
        schema = (spec or {}).get("param_schema") or {}
        props = (schema.get("properties") or {})
        if key not in props:
            raise ToolError(
                code="PARAM_NOT_IN_SCHEMA",
                message=f"Block '{node.block_id}' has no parameter '{key}'",
                hint=f"Allowed keys: {sorted(props.keys())}",
            )
        prop = props[key]
        # Reject `$xxx` placeholders that don't match a declared input before
        # the value lands on canvas via SSE — see _check_placeholder_declared.
        # Done before enum check because $xxx never matches an enum literally.
        _check_placeholder_declared(pipeline, value, param_key=key, node_id=node_id)
        # 2026-05-04: column-ref validation. If this param references an
        # upstream column (sort.column / filter.column / chart.x / etc.)
        # and the upstream's output schema is computable, reject obviously
        # wrong names (e.g. 'count' when upstream groupby_agg emits
        # 'spc_status_count'). LLM gets a clear hint instead of finding
        # out at auto-run time.
        _check_column_in_upstream(
            pipeline, node, self.registry,
            param_key=key, value=value,
        )
        enum = prop.get("enum")
        # Skip enum check for $xxx placeholders — they're resolved at runtime,
        # so the literal "$tool_id" wouldn't satisfy any concrete enum.
        is_placeholder = isinstance(value, str) and value.startswith("$")
        if (
            enum is not None
            and not is_placeholder
            and value not in enum
            and value is not None
            and value != ""
        ):
            raise ToolError(
                code="PARAM_ENUM_VIOLATION",
                message=f"Value {value!r} not in allowed enum for '{key}': {enum}",
            )
        node.params = {**node.params, key: value}
        return {"node_id": node_id, "params": dict(node.params)}

    async def declare_input(
        self,
        name: str,
        type: str = "string",
        required: bool = True,
        example: Optional[Any] = None,
        description: str = "",
    ) -> dict[str, Any]:
        """SPEC_patrol_pipeline_wiring §1.5 — declare a `$name` pipeline input.

        Use this **before** writing a user-mentioned instance value (EQP-XX,
        STEP_XXX, LOT-XXX, lot_id, recipe_id, ...) into a node param. After
        declaring, reference the variable as `$name` in set_param so the
        pipeline is reusable across patrols / lots / runs.

        Idempotent: declaring the same name twice updates example/description
        instead of raising.
        """
        from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineInput

        valid_types = {"string", "integer", "number", "boolean"}
        if type not in valid_types:
            raise ToolError(
                code="INVALID_PARAM",
                message=f"type '{type}' invalid (allowed: {sorted(valid_types)})",
            )
        if not name or not name.strip():
            raise ToolError(code="INVALID_PARAM", message="input name is required")
        nm = name.lstrip("$").strip()  # accept "$equipment_id" or "equipment_id"
        if not nm.isidentifier():
            raise ToolError(
                code="INVALID_PARAM",
                message=f"input name '{nm}' must be a valid identifier (letters/digits/underscore)",
            )

        pipeline = self.session.pipeline_json
        existing = next((i for i in pipeline.inputs if i.name == nm), None)
        if existing is not None:
            # idempotent: refresh example / description
            if example is not None:
                existing.example = example
            if description:
                existing.description = description
            existing.required = bool(required)
            existing.type = type  # type: ignore[assignment]
            return {"input": existing.model_dump(), "updated": True}

        new_input = PipelineInput(
            name=nm,
            type=type,  # type: ignore[arg-type]
            required=bool(required),
            example=example,
            description=description or None,
        )
        pipeline.inputs = list(pipeline.inputs) + [new_input]
        return {"input": new_input.model_dump(), "created": True}

    async def move_node(self, node_id: str, position: dict[str, float]) -> dict[str, Any]:
        pipeline = self.session.pipeline_json
        node = next((n for n in pipeline.nodes if n.id == node_id), None)
        if node is None:
            raise ToolError(code="NODE_NOT_FOUND", message=f"Node '{node_id}' not in pipeline")
        node.position = NodePosition(x=float(position["x"]), y=float(position["y"]))
        return {"node_id": node_id, "position": position}

    async def rename_node(self, node_id: str, label: str) -> dict[str, Any]:
        pipeline = self.session.pipeline_json
        node = next((n for n in pipeline.nodes if n.id == node_id), None)
        if node is None:
            raise ToolError(code="NODE_NOT_FOUND", message=f"Node '{node_id}' not in pipeline")
        node.display_label = label
        return {"node_id": node_id, "display_label": label}

    # ======================================================================
    # Plan Panel (v1.4) — Glass Box-side equivalent of orchestrator's update_plan.
    # The result dict is recognised by orchestrator.py and converted to a
    # "plan" or "plan_update" StreamEvent so the Frontend can render the
    # checklist live.
    # ======================================================================

    async def update_plan(
        self,
        action: str,
        items: Optional[list] = None,
        id: Optional[str] = None,  # noqa: A002 — schema field name
        status: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict[str, Any]:
        action = (action or "create").lower()
        if action == "create":
            return {
                "_plan_action": "create",
                "items": items or [],
                "status": "success",
            }
        if action == "update":
            return {
                "_plan_action": "update",
                "id": id,
                "status_value": status,
                "note": note,
                "status": "success",
            }
        raise ToolError(
            code="BAD_PLAN_ACTION",
            message="update_plan.action must be 'create' or 'update'",
        )

    # ======================================================================
    # Introspection (3)
    # ======================================================================

    async def get_state(self) -> dict[str, Any]:
        p = self.session.pipeline_json
        return {
            "name": p.name,
            "node_count": len(p.nodes),
            "edge_count": len(p.edges),
            "nodes": [
                {
                    "id": n.id,
                    "block_id": n.block_id,
                    "params": dict(n.params),
                }
                for n in p.nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "from": {"node": e.from_.node, "port": e.from_.port},
                    "to": {"node": e.to.node, "port": e.to.port},
                }
                for e in p.edges
            ],
        }

    async def preview(self, node_id: str, sample_size: int = 50) -> dict[str, Any]:
        """Execute pipeline up to node_id and return its output summary.

        Returned fields depend on output type:
          - dataframe: {status, columns, rows_sample (≤ sample_size), total, error?}
          - dict (e.g. chart_spec): {status, value_summary, error?}
        """
        pipeline = self.session.pipeline_json
        node_ids = {n.id for n in pipeline.nodes}
        if node_id not in node_ids:
            raise ToolError(code="NODE_NOT_FOUND", message=f"Node '{node_id}' not in pipeline")

        # Truncate to ancestors + target
        ancestors = {node_id}
        frontier = {node_id}
        while frontier:
            nxt: set[str] = set()
            for e in pipeline.edges:
                if e.to.node in frontier and e.from_.node not in ancestors:
                    ancestors.add(e.from_.node)
                    nxt.add(e.from_.node)
            frontier = nxt

        truncated = pipeline.model_copy(
            update={
                "nodes": [n for n in pipeline.nodes if n.id in ancestors],
                "edges": [e for e in pipeline.edges if e.from_.node in ancestors and e.to.node in ancestors],
            }
        )

        # Validate subgraph but skip C7 (partial pipeline allowed)
        validator = PipelineValidator(self.registry.catalog)
        errors = [e for e in validator.validate(truncated) if e.get("rule") != "C7_ENDPOINTS"]
        if errors:
            return {
                "status": "validation_error",
                "errors": errors,
            }

        result = await self.executor.execute(truncated, preview_sample_size=sample_size)
        node_result = result["node_results"].get(node_id) or {}
        return {
            "status": node_result.get("status", "unknown"),
            "rows": node_result.get("rows"),
            "duration_ms": node_result.get("duration_ms"),
            "error": node_result.get("error"),
            "preview": _summarize_preview(node_result.get("preview"), sample_size),
        }

    async def validate(self) -> dict[str, Any]:
        validator = PipelineValidator(self.registry.catalog)
        errs = validator.validate(self.session.pipeline_json)

        # SPEC_patrol_pipeline_wiring §1.5 — declared-but-unused warnings.
        # Catches the case where the agent declared an input but forgot to
        # actually reference $name in any node param. Doesn't fail validation
        # (the pipeline still runs with default values) but flags so the agent
        # has a chance to fix before finish.
        warnings: list[dict[str, Any]] = []
        pipeline = self.session.pipeline_json
        declared_names = {inp.name for inp in (pipeline.inputs or [])}
        if declared_names:
            referenced: set[str] = set()
            for n in pipeline.nodes:
                for v in (n.params or {}).values():
                    if isinstance(v, str) and v.startswith("$"):
                        referenced.add(v[1:].split(".")[0])
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str) and item.startswith("$"):
                                referenced.add(item[1:].split(".")[0])
            unused = declared_names - referenced
            if unused:
                warnings.append({
                    "code": "INPUT_DECLARED_BUT_UNUSED",
                    "message": f"Inputs declared but never referenced: {sorted(unused)}",
                    "hint": "Did you forget to set_param(node, key, '$<name>')? Or remove the input if it's not needed.",
                })

        # Phase 11 v11 — warn when a required input lacks both default and
        # example. Auto-Run preview will fall back to a canonical literal
        # (executor _CANONICAL_INPUT_FALLBACKS) if name matches; otherwise
        # it red-banners. Either way, the agent should set example so the
        # intent is explicit.
        for inp in (pipeline.inputs or []):
            if not getattr(inp, "required", False):
                continue
            if getattr(inp, "default", None) is not None:
                continue
            if getattr(inp, "example", None) is not None:
                continue
            warnings.append({
                "code": "INPUT_MISSING_EXAMPLE",
                "message": f"Required input '{inp.name}' has no default or example.",
                "hint": (
                    f"Call declare_input('{inp.name}', example='<a real value e.g. EQP-01>') "
                    "so Auto-Run preview has something to fill. Without this the canvas red-banners."
                ),
            })

        return {"valid": len(errs) == 0, "errors": errs, "warnings": warnings}

    # ======================================================================
    # Communication (1 in MVP)
    # ======================================================================

    async def explain(
        self,
        message: str,
        highlight_nodes: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        msg = ChatMsg(content=message, highlight_nodes=highlight_nodes or [])
        self.session.record_chat(msg)
        return {"chat_appended": True}

    async def suggest_action(
        self,
        summary: str,
        actions: list[dict[str, Any]],
        rationale: Optional[str] = None,
    ) -> dict[str, Any]:
        """PR-E3b: Record a proposal (does NOT apply). Orchestrator emits the
        suggestion_card event; frontend renders and lets user apply/dismiss."""
        # Lightweight validation: each action must name a known tool + dict args
        allowed = {"add_node", "connect", "set_param", "rename_node", "remove_node"}
        for a in actions:
            if not isinstance(a, dict):
                raise ToolError(code="INVALID_SUGGESTION", message="Each action must be an object")
            tool = a.get("tool")
            if tool not in allowed:
                raise ToolError(
                    code="INVALID_SUGGESTION",
                    message=f"Action tool '{tool}' not allowed (must be one of {sorted(allowed)})",
                )
            if not isinstance(a.get("args"), dict):
                raise ToolError(code="INVALID_SUGGESTION", message="Each action needs an 'args' object")
        return {
            "suggestion_recorded": True,
            "summary": summary,
            "rationale": rationale,
            "actions": actions,
        }

    # ======================================================================
    # Lifecycle (1)
    # ======================================================================

    async def finish(self, summary: str) -> dict[str, Any]:
        """Mark session finished. GATE: validate() must pass first."""
        validator = PipelineValidator(self.registry.catalog)
        errs = validator.validate(self.session.pipeline_json)
        if errs:
            raise ToolGateError(
                code="FINISH_BLOCKED",
                message=(
                    f"Cannot finish — validator reported {len(errs)} error(s). "
                    "Fix them first, then call finish again."
                ),
                hint=json.dumps(errs[:3], ensure_ascii=False),
            )
        self.session.mark_finished(summary=summary)
        return {"status": "finished", "summary": summary}


# ---------------------------------------------------------------------------
# Preview summarization helper
# ---------------------------------------------------------------------------

def _summarize_preview(preview: Optional[dict[str, Any]], sample_size: int) -> dict[str, Any]:
    """Convert executor's preview dict into a compact LLM-friendly summary."""
    if not preview:
        return {}
    summary: dict[str, Any] = {}
    for port, block in preview.items():
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "dataframe":
            rows = block.get("rows") or []
            summary[port] = {
                "type": "dataframe",
                "columns": block.get("columns"),
                "total_rows": block.get("total"),
                "sample_rows": rows[: min(sample_size, 5)],  # keep LLM input small
            }
        elif t == "dict":
            snap = block.get("snapshot")
            # chart_spec can be huge; summarize
            if isinstance(snap, dict) and "mark" in snap and "encoding" in snap:
                summary[port] = {
                    "type": "chart_spec",
                    "mark": snap.get("mark"),
                    "encoding": snap.get("encoding"),
                    "data_values_count": len((snap.get("data") or {}).get("values") or []),
                }
                _attach_chart_warnings(summary[port], snap)
            elif isinstance(snap, dict) and snap.get("__dsl") is True:
                # New SVG-engine chart_spec
                summary[port] = {
                    "type": "chart_spec",
                    "chart_type": snap.get("type"),
                    "x": snap.get("x"),
                    "y": snap.get("y"),
                    "data_values_count": len(snap.get("data") or []),
                }
                _attach_chart_warnings(summary[port], snap)
            else:
                summary[port] = {"type": "dict", "keys": list((snap or {}).keys())[:20]}
        elif t == "list":
            summary[port] = {"type": "list", "length": block.get("length"), "sample": block.get("sample")}
        else:
            summary[port] = {"type": t, "value": block.get("value")}
    return summary


# ── Self-test: chart x_key ISO8601 validation ─────────────────────────────────
# Stage-2 follow-up. We've burned hours on chart_spec shape mismatches before
# (`block_chart_facet` SPC trend with x_key='timestamp' but values were integer
# indices). When the chart's x column name suggests a time field but the
# rendered values aren't ISO8601, warn the LLM in the preview summary so it
# can patch params without waiting for visual feedback.

# Lightweight ISO8601 sniffer — same regex shape as charts/lib/axis.ts.
_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
_TIME_KEY_HINTS = ("time", "Time", "TIME", "date", "Date", "timestamp", "Timestamp")


def _looks_like_iso(v: Any) -> bool:
    if isinstance(v, str):
        return bool(_ISO_DATE_RE.match(v.strip()))
    return False


def _attach_chart_warnings(summary_out: dict[str, Any], spec: dict[str, Any]) -> None:
    """Append a `warnings` list when the chart spec has likely-wrong x values.

    Detects: x column name contains a time hint (eventTime / timestamp /
    date_recorded …) but the first non-null data value isn't ISO8601 — almost
    certainly the producer forgot to coerce or used the wrong field.
    """
    warnings: list[str] = []

    x = spec.get("x")
    data = spec.get("data") or []
    if isinstance(x, str) and any(h in x for h in _TIME_KEY_HINTS):
        # Look at first 3 non-null values to avoid one stray null tripping the check.
        sample_values = []
        for row in data[:10]:
            if isinstance(row, dict):
                v = row.get(x)
                if v is not None:
                    sample_values.append(v)
                    if len(sample_values) >= 3:
                        break
        if sample_values and not any(_looks_like_iso(v) for v in sample_values):
            warnings.append(
                f"x column '{x}' looks like a time field but values are not ISO8601 "
                f"(first sample: {sample_values[0]!r}). Cast upstream with "
                f"`block_compute` (e.g. expression: `as_iso8601`) or pick the right "
                f"column."
            )

    if warnings:
        summary_out["warnings"] = warnings
