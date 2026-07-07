"""Orphan resolution (2026-06-18, ENABLE_ORPHAN_RESOLVE).

A node that is fully disconnected — no inbound AND no outbound edge — is dead
weight that trips the finalize structural check (failed_structural), failing the
WHOLE build even when the rest of the pipeline is correct (spc-ooc: a stray
process_history left over from an early wrong add).

Rather than silently fail OR silently prune (which could delete a node the agent
meant to wire), give the agent ONE round to JUDGE: connect each orphan into the
pipeline, or remove it. Called inline at the top of finalize_node when the flag
is on; a single shot — if the agent doesn't clean it, finalize fails as before
(no worse than today).
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.feature_flags import is_orphan_resolve_enabled

logger = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "connect",
        "description": "Wire one node's output into another's input.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_node": {"type": "string"}, "from_port": {"type": "string"},
                "to_node": {"type": "string"}, "to_port": {"type": "string"},
            },
            "required": ["from_node", "to_node"],
        },
    },
    {
        "name": "remove_node",
        "description": "Delete a node by id (use for a dead/redundant orphan).",
        "input_schema": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
    },
]


def _isolated_nodes(pipe: dict) -> list[dict]:
    """Nodes with neither inbound nor outbound edge. A 1-node pipeline is the
    whole pipeline (source=terminal), not an orphan."""
    nodes = pipe.get("nodes") or []
    if len(nodes) <= 1:
        return []
    edges = pipe.get("edges") or []
    inb = {(e.get("to") or {}).get("node") for e in edges}
    outb = {(e.get("from") or {}).get("node") for e in edges}
    return [n for n in nodes if n.get("id") not in inb and n.get("id") not in outb]


def _describe(pipe: dict, isolated: list[dict]) -> str:
    lines = ["當前 pipeline:"]
    for n in pipe.get("nodes") or []:
        lines.append(f"  {n.get('id')} = {n.get('block_id')}  params={n.get('params') or {}}")
    lines.append("edges: " + ", ".join(
        f"{(e.get('from') or {}).get('node')}->{(e.get('to') or {}).get('node')}"
        for e in (pipe.get("edges") or [])
    ))
    lines.append("")
    lines.append("以下 node 完全沒接上 pipeline(沒有上游也沒有下游),會讓 build 結構檢查失敗:")
    for n in isolated:
        lines.append(f"  ⚠ {n.get('id')} = {n.get('block_id')}  params={n.get('params') or {}}")
    lines.append("")
    lines.append("請你判斷:每個孤兒 node 要嘛 connect 接進 pipeline(若它確實該在流程裡),"
                 "要嘛 remove_node 砍掉(若它是多餘/誤加的死碼)。每個孤兒發一個 tool call。")
    return "\n".join(lines)


_SYSTEM = (
    "你在收尾一個 pipeline build。有 node 沒接上 pipeline。你的工作:對每個孤兒 node,"
    "決定 connect(接進流程)或 remove_node(砍掉死碼)。只發 tool call,不要解釋。"
)


async def maybe_resolve_orphans(state: dict) -> dict[str, Any]:
    """If isolated orphans exist, run one agent round to connect/remove them.
    Returns {'final_pipeline': cleaned} when it changed the pipeline, else {}.
    Never raises — best-effort cleanup before finalize."""
    if not is_orphan_resolve_enabled():
        return {}
    pipe = state.get("final_pipeline") or state.get("base_pipeline") or {}
    isolated = _isolated_nodes(pipe)
    if not isolated:
        return {}
    try:
        from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
        from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
        from python_ai_sidecar.agent_builder.session import AgentBuilderSession
        from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
        from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
        from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
            _extract_assistant_content,
        )

        registry = SeedlessBlockRegistry()
        registry.load()
        pj = PipelineJSON.model_validate(pipe)
        session = AgentBuilderSession.new(
            user_prompt=state.get("instruction", ""), base_pipeline=pj,
        )
        from python_ai_sidecar.pipeline_builder.source_cache import get_session_cache
        toolset = BuilderToolset(
            session, registry,
            source_cache=get_session_cache(str(state.get("session_id") or "anon")),
        )

        client = get_llm_client()
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": _describe(pipe, isolated)}],
            tools=_TOOLS,
            max_tokens=1024,
        )
        blocks = _extract_assistant_content(resp) or []
        applied = 0
        for blk in blocks:
            if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                continue
            name = blk.get("name")
            args = blk.get("input") or {}
            if name not in ("connect", "remove_node"):
                continue
            try:
                await getattr(toolset, name)(**args)
                applied += 1
            except ToolError as e:
                logger.info("orphan_resolve: %s failed: %s", name, e.message)
            except Exception as e:  # noqa: BLE001
                logger.info("orphan_resolve: %s threw: %s", name, e)
        if applied == 0:
            return {}
        new_pipe = session.pipeline_json.model_dump(by_alias=True)
        remaining = _isolated_nodes(new_pipe)
        logger.info("orphan_resolve: applied %d action(s); orphans %d -> %d",
                    applied, len(isolated), len(remaining))
        return {"final_pipeline": new_pipe}
    except Exception as ex:  # noqa: BLE001 — never break finalize
        logger.info("orphan_resolve skipped (%s)", ex)
        return {}
