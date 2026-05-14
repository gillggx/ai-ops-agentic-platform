"""confirm_gate_node — emit confirm_pending SSE then interrupt the graph.

LangGraph's `interrupt()` pauses the graph and persists state via the
configured checkpointer. The runner returns control to the SSE handler,
which yields confirm_pending and ends the stream. Resume happens when
the frontend POSTs /agent/build/{session_id}/confirm; the runner calls
graph.invoke(Command(resume=confirmed), ...) to continue from here.

Only triggered when state.is_from_scratch is True. INCREMENTAL skips
straight to dispatch (graph routing decides this, not us).
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)


async def confirm_gate_node(state: BuildGraphState) -> dict[str, Any]:
    plan_summary = state.get("summary") or "(no summary)"
    plan = state.get("plan") or []
    structured_outputs = state.get("expected_outputs_structured") or []
    numbered_steps = _numbered_steps(plan)
    macro_plan = state.get("macro_plan") or []
    step_outputs = state.get("step_outputs") or {}
    dag_payload = _build_dag_payload(plan, macro_plan, step_outputs)

    logger.info(
        "confirm_gate_node: pausing for user confirm (session=%s, %d ops, %d structured outputs, dag.nodes=%d edges=%d)",
        state.get("session_id"), len(plan), len(structured_outputs),
        len(dag_payload.get("nodes") or []), len(dag_payload.get("edges") or []),
    )

    # The interrupt payload is what the runner sees in the resulting
    # __interrupt__ marker — used to emit confirm_pending SSE.
    # v15 G2: add numbered_steps + expected_outputs_structured so the
    # frontend can render the upgraded review card with "改 step N" path.
    # v20: add dag {nodes, edges, mermaid} so the frontend renders the DAG
    # diagram (parallel branches visible) instead of an implied linear chain.
    user_response = interrupt({
        "session_id": state.get("session_id"),
        "plan_summary": plan_summary,
        "expected_outputs": state.get("expected_outputs") or [],
        "expected_outputs_structured": structured_outputs,
        "plan_ops": [_op_summary(op) for op in plan],
        "numbered_steps": numbered_steps,
        "n_ops": len(plan),
        # echo clarifications so frontend can show "agent answered: X"
        "clarifications_applied": state.get("clarifications") or {},
        "dag": dag_payload,
    })

    # When resumed, user_response shape:
    #   confirm yes:    {"confirmed": True}
    #   confirm no:     {"confirmed": False}
    #   modify request: {"modify": True, "step_idx": int|None, "request": str}
    is_modify = (
        isinstance(user_response, dict)
        and bool(user_response.get("modify"))
    )
    if is_modify:
        step_idx = user_response.get("step_idx")
        req_text = str(user_response.get("request") or "").strip()
        modify_requests = list(state.get("modify_requests") or [])
        modify_requests.append({
            "step_idx": step_idx,
            "request": req_text,
            "at_cycle": state.get("modify_cycles", 0),
        })
        cycles = state.get("modify_cycles", 0) + 1
        logger.info(
            "confirm_gate_node: resumed with MODIFY (step_idx=%s, cycle=%d)",
            step_idx, cycles,
        )
        # user_confirmed=None signals "replan, not approve, not reject"
        # — graph route reads modify_requests / modify_cycles to decide.
        return {
            "user_confirmed": None,
            "modify_requests": modify_requests,
            "modify_cycles": cycles,
            "sse_events": [_event("modify_requested", {
                "step_idx": step_idx, "request": req_text[:200], "cycle": cycles,
            })],
        }

    confirmed = bool(user_response.get("confirmed")) if isinstance(user_response, dict) else bool(user_response)
    logger.info("confirm_gate_node: resumed with confirmed=%s", confirmed)

    return {
        "user_confirmed": confirmed,
        "sse_events": [_event("confirm_received", {"confirmed": confirmed})],
    }


def _numbered_steps(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """v15 G2: derive human-readable numbered steps from plan ops.

    Walks add_node + set_param ops in plan order, producing one step per
    add_node with the configured params merged in. Skips connect/preview
    (rendered as edges, not standalone steps).
    """
    # First pass: collect node ops with their params
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for op in plan:
        t = op.get("type")
        if t == "add_node":
            lid = op.get("node_id") or f"n{len(order) + 1}"
            nodes[lid] = {
                "logical_id": lid,
                "block_id": op.get("block_id"),
                "params": dict(op.get("params") or {}),
            }
            order.append(lid)
        elif t == "set_param":
            lid = op.get("node_id")
            kv = op.get("params") or {}
            k, v = kv.get("key"), kv.get("value")
            if lid in nodes and k is not None:
                nodes[lid]["params"][k] = v
    # Render
    out: list[dict[str, Any]] = []
    for i, lid in enumerate(order, 1):
        n = nodes[lid]
        params = n["params"]
        # Compact param string
        param_parts: list[str] = []
        for k, v in list(params.items())[:6]:
            sv = repr(v) if not isinstance(v, str) else v
            if len(sv) > 30:
                sv = sv[:30] + "…"
            param_parts.append(f"{k}={sv}")
        params_str = ", ".join(param_parts) if param_parts else ""
        out.append({
            "step_idx": i,
            "logical_id": lid,
            "block_id": n["block_id"],
            "params_summary": params_str,
            "description": f"{n['block_id']}({params_str})" if params_str else n["block_id"] or "?",
        })
    return out


def _op_summary(op_dict: dict[str, Any]) -> str:
    """Compact one-line summary for confirm card."""
    t = op_dict.get("type", "?")
    if t == "add_node":
        return f"add {op_dict.get('block_id')} (as {op_dict.get('node_id', '?')})"
    if t == "connect":
        return f"connect {op_dict.get('src_id')}.{op_dict.get('src_port')} → {op_dict.get('dst_id')}.{op_dict.get('dst_port')}"
    if t == "set_param":
        p = op_dict.get("params") or {}
        return f"{op_dict.get('node_id')}.{p.get('key', '?')} = {p.get('value', '?')!r}"
    if t == "run_preview":
        return f"preview {op_dict.get('node_id')}"
    if t == "remove_node":
        return f"remove {op_dict.get('node_id')}"
    return t


def _build_dag_payload(
    plan: list[dict[str, Any]],
    macro_plan: list[dict[str, Any]],
    step_outputs: dict[Any, list[str]],
) -> dict[str, Any]:
    """v20: shape DAG payload for the confirm card (Skill Builder + chat).

    Returns:
      {
        "nodes": [{logical_id, block_id, label, step_idx?}],
        "edges": [{src, dst, label?}],   # actual connect ops in the plan
        "mermaid": "graph TD\\n  n1[block_process_history]\\n  n1 --> n2\\n  ...",
        "macro_steps": [{step_idx, text, depends_on, candidate_block, produced}],
      }

    `nodes` + `edges` come from the actual plan (ground truth — what runtime
    will execute). `macro_steps` echoes macro_plan so the card can show the
    high-level intent alongside. `mermaid` is a pre-rendered diagram string
    the frontend can pipe to mermaid.js.
    """
    nodes: list[dict[str, Any]] = []
    seen_lid: set[str] = set()
    for op in plan:
        if op.get("type") == "add_node":
            lid = str(op.get("node_id") or "")
            if not lid or lid in seen_lid:
                continue
            seen_lid.add(lid)
            nodes.append({
                "logical_id": lid,
                "block_id": op.get("block_id"),
                "label": op.get("block_id") or lid,
            })

    edges: list[dict[str, Any]] = []
    for op in plan:
        if op.get("type") == "connect":
            src = str(op.get("src_id") or "")
            dst = str(op.get("dst_id") or "")
            if src and dst:
                edges.append({
                    "src": src, "dst": dst,
                    "label": (op.get("src_port") or "") + "→" + (op.get("dst_port") or ""),
                })

    # Annotate each node with which macro step produced it (best-effort).
    lid_to_step: dict[str, int] = {}
    for s in macro_plan:
        sidx = s.get("step_idx")
        outs = step_outputs.get(sidx) or step_outputs.get(str(sidx)) or []
        for lid in outs:
            lid_to_step[str(lid)] = int(sidx) if sidx is not None else 0
    for n in nodes:
        sidx = lid_to_step.get(n["logical_id"])
        if sidx is not None:
            n["step_idx"] = sidx

    # Pre-render mermaid (graph TD). Logical id is mermaid-safe by convention
    # (n1, n2, ...). Label = block_id (truncated). Edges as `n1 --> n2`.
    mermaid_lines = ["graph TD"]
    for n in nodes:
        block = (n.get("block_id") or "?").replace("\"", "'")[:30]
        mermaid_lines.append(f'  {n["logical_id"]}["{n["logical_id"]}: {block}"]')
    for e in edges:
        mermaid_lines.append(f'  {e["src"]} --> {e["dst"]}')
    mermaid = "\n".join(mermaid_lines)

    macro_steps_out = [
        {
            "step_idx": s.get("step_idx"),
            "text": s.get("text"),
            "depends_on": s.get("depends_on") or [],
            "candidate_block": s.get("candidate_block"),
            "expected_kind": s.get("expected_kind"),
            "produced": step_outputs.get(s.get("step_idx"))
                or step_outputs.get(str(s.get("step_idx"))) or [],
        }
        for s in macro_plan
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "mermaid": mermaid,
        "macro_steps": macro_steps_out,
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
