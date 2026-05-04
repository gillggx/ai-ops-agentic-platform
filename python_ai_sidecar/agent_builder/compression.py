"""Glass Box conversation history compression.

Why:
  Anthropic prompt cache covers system + tools across turns, but the
  growing message list (assistant + tool_result × N turns) is sent fresh
  every call. By turn 10+, cumulative history can dwarf the cached
  prefix. Profiling on prod 2026-05-04 caught builds spending more on
  uncached history replay than on actual reasoning.

How:
  Replace older (assistant, tool_result) pairs with one synthetic
  assistant message holding a deterministic synopsis derived from
  ``session.operations`` + ``session.pipeline_json``. Recent turns
  (configurable window) stay as-is so the LLM still sees fresh
  reasoning context.

Trade-off:
  Pure deterministic — no extra LLM call. Loses the assistant's prior
  *thinking* text but keeps every canvas-mutating action (the
  authoritative state). Validated against the agent eval suite.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional

from python_ai_sidecar.agent_builder.session import AgentBuilderSession, Operation


log = logging.getLogger(__name__)


# How many turn pairs (assistant + tool_result) at the tail of the history
# to keep verbatim. Older pairs collapse into a single synopsis message.
COMPRESSION_WINDOW = 5

# Don't compress until the total history is larger than this many turn
# pairs. Short builds pay zero overhead; long builds get the squeeze.
COMPRESSION_TRIGGER_TURNS = 8

# Tool ops that mutate the canvas — surface in synopsis. Anything not on
# this list is read-only and only counted (e.g. list_blocks, get_state).
_MUTATION_OPS = frozenset({
    "add_node",
    "remove_node",
    "set_param",
    "rename_node",
    "connect",
    "disconnect",
    "declare_input",
    "remove_input",
})

# Tool ops where the result content is verbose (preview rows, validate
# error lists). When kept inside the recent window, these can still be
# truncated to spare tokens.
_VERBOSE_RESULT_OPS = frozenset({
    "validate",
    "run_preview",
    "preview",
    "get_state",
    "list_blocks",
    "explain_block",
})


# ---------------------------------------------------------------------------
# Synopsis renderer — pure function
# ---------------------------------------------------------------------------


def _render_op_synopsis(
    operations: list[Operation],
    pipeline_json_dict: dict[str, Any],
    *,
    read_only_op_count: int = 0,
) -> str:
    """Render a deterministic synopsis of past operations + current canvas.

    Format (markdown, ~300-800 tokens for a typical 10-op build):

        Earlier in this build I performed these canvas operations:
        - n1 added (block_process_history) [tool_id="$tool_id", time_range="24h"]
        - n2 added (block_filter) [column="spc_status", operator="==", value="OOC"]
        - edge n1.data → n2.data
        ... + 4 read-only checks (list_blocks / explain_block / preview).

        Current canvas state:
          inputs:  [tool_id (string, example=EQP-01)]
          nodes:   2  ·  edges: 1
          n1: block_process_history  · params: { tool_id: "$tool_id", ... }
          n2: block_filter  · params: { column: "spc_status", operator: "==", value: "OOC" }
    """
    if not operations and not pipeline_json_dict.get("nodes"):
        return ""

    lines: list[str] = []
    lines.append("Earlier in this build I performed these canvas operations:")

    mutation_lines: list[str] = []
    for op in operations:
        if op.op not in _MUTATION_OPS:
            continue
        rendered = _render_one_mutation(op)
        if rendered:
            mutation_lines.append(rendered)

    if mutation_lines:
        lines.extend(mutation_lines)
    else:
        lines.append("- (no canvas-mutating ops yet)")

    if read_only_op_count > 0:
        lines.append(
            f"- … plus {read_only_op_count} read-only check(s) "
            "(list_blocks / explain_block / preview / get_state)."
        )

    # Snapshot current canvas — authoritative state, NOT replayed from ops.
    nodes = pipeline_json_dict.get("nodes") or []
    edges = pipeline_json_dict.get("edges") or []
    inputs = pipeline_json_dict.get("inputs") or []

    lines.append("")
    lines.append("Current canvas state:")
    if inputs:
        decls = []
        for inp in inputs:
            ex = inp.get("example") or inp.get("default")
            decls.append(
                f"{inp.get('name')} ({inp.get('type', 'string')}"
                + (f", example={ex!r}" if ex is not None else "")
                + ")"
            )
        lines.append(f"  inputs:  [{', '.join(decls)}]")
    lines.append(f"  nodes:   {len(nodes)}  ·  edges: {len(edges)}")
    for node in nodes:
        node_id = node.get("id")
        block_id = node.get("block_id")
        params = node.get("params") or {}
        # Compact param render — params are usually small strings/numbers
        compact_params = json.dumps(params, ensure_ascii=False)
        if len(compact_params) > 200:
            compact_params = compact_params[:200] + "…"
        lines.append(f"  {node_id}: {block_id}  · params: {compact_params}")

    return "\n".join(lines)


def _render_one_mutation(op: Operation) -> str:
    """Render one canvas-mutating operation as a single bullet line."""
    args = op.args or {}
    if op.op == "add_node":
        nid = (op.result or {}).get("node_id", "?")
        block = args.get("block_name", "?")
        return f"- {nid} added ({block})"
    if op.op == "remove_node":
        return f"- {args.get('node_id', '?')} removed"
    if op.op == "set_param":
        node_id = args.get("node_id", "?")
        key = args.get("key", "?")
        value = args.get("value")
        # Truncate huge values
        v = json.dumps(value, ensure_ascii=False, default=str)
        if len(v) > 80:
            v = v[:80] + "…"
        return f"- {node_id}.{key} set to {v}"
    if op.op == "rename_node":
        return f"- {args.get('node_id', '?')} renamed to {args.get('label', '?')!r}"
    if op.op == "connect":
        return f"- edge {args.get('from_node', '?')}.{args.get('from_port', 'data')}" \
               f" → {args.get('to_node', '?')}.{args.get('to_port', 'data')}"
    if op.op == "disconnect":
        return f"- edge {args.get('edge_id', '?')} removed"
    if op.op == "declare_input":
        nm = args.get("name", "?")
        ex = args.get("example")
        suffix = f" (example={ex!r})" if ex is not None else ""
        return f"- input ${nm} declared{suffix}"
    if op.op == "remove_input":
        return f"- input ${args.get('name', '?')} removed"
    return f"- {op.op}({args})"


# ---------------------------------------------------------------------------
# Tool result truncation — applied to retained recent-turn messages
# ---------------------------------------------------------------------------


def _truncate_tool_result(tool_name: str, content_str: str) -> str:
    """Trim verbose tool results to a head-only summary.

    Applied to results retained in the recent window so even those don't
    balloon. Keeps the structure intact (LLM still sees JSON) but caps
    long lists at a few entries with a footer.
    """
    if tool_name not in _VERBOSE_RESULT_OPS:
        return content_str
    try:
        obj = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return content_str
    obj = _truncate_obj(tool_name, obj)
    return json.dumps(obj, ensure_ascii=False, default=str)


def _truncate_obj(tool_name: str, obj: Any) -> Any:
    if not isinstance(obj, dict):
        return obj

    # validate: keep first 3 errors out of N
    if tool_name == "validate" and "errors" in obj:
        errs = obj.get("errors") or []
        if isinstance(errs, list) and len(errs) > 3:
            obj = {**obj, "errors": errs[:3] + [{"_truncated": f"{len(errs) - 3} more error(s)"}]}

    # run_preview / preview: keep first 5 rows of any 'rows' / 'sample'
    if tool_name in ("run_preview", "preview"):
        for key in ("rows", "sample"):
            rows = obj.get(key)
            if isinstance(rows, list) and len(rows) > 5:
                obj = {**obj, key: rows[:5] + [{"_truncated": f"{len(rows) - 5} more row(s)"}]}

    # list_blocks: shouldn't be huge any more (slim catalog); still cap at 20
    if tool_name == "list_blocks" and "blocks" in obj:
        bs = obj.get("blocks") or []
        if isinstance(bs, list) and len(bs) > 20:
            obj = {**obj, "blocks": bs[:20] + [{"_truncated": f"{len(bs) - 20} more block(s)"}]}

    # explain_block: keep description but trim verbose examples list
    if tool_name == "explain_block" and "examples" in obj:
        ex = obj.get("examples") or []
        if isinstance(ex, list) and len(ex) > 3:
            obj = {**obj, "examples": ex[:3]}

    # get_state: keep only top-level summary numbers if oversized
    if tool_name == "get_state":
        # Best-effort: drop verbose 'preview' if present
        if "preview" in obj and isinstance(obj["preview"], (list, dict)):
            obj = {**obj, "preview": "<truncated for history compression>"}

    return obj


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compress_messages(
    messages: list[dict[str, Any]],
    session: AgentBuilderSession,
    *,
    window: int = COMPRESSION_WINDOW,
    trigger_turns: int = COMPRESSION_TRIGGER_TURNS,
) -> list[dict[str, Any]]:
    """Return a possibly-compressed copy of the message list.

    Compression happens only when there are more than ``trigger_turns``
    assistant/user turn pairs in the history. Messages[0] (the user's
    original prompt) is always preserved as the task anchor; a synthetic
    assistant message is inserted right after it that summarizes
    everything before the recent window.

    Tool results within the retained window are also truncated for the
    verbose ones (validate / preview / etc.).

    Falls back to returning ``messages`` unchanged on any internal error
    so a compression bug never breaks a build.
    """
    try:
        return _compress_messages_impl(messages, session, window, trigger_turns)
    except Exception as exc:  # noqa: BLE001
        log.warning("compress_messages failed (%s) — falling back to original history", exc)
        return messages


def _compress_messages_impl(
    messages: list[dict[str, Any]],
    session: AgentBuilderSession,
    window: int,
    trigger_turns: int,
) -> list[dict[str, Any]]:
    if len(messages) < 3:
        return messages

    # Estimate "turn pairs" = (assistant, user-with-tool-results) doublets
    # past the initial user prompt.
    turn_pairs = max(0, (len(messages) - 1) // 2)
    if turn_pairs <= trigger_turns:
        # Still apply tool_result truncation in-place to the window
        return [_truncate_recent_msg(m) for m in messages]

    # Decide cutoff. Keep messages[0] (user prompt) + last (window × 2) msgs.
    keep_tail = window * 2
    head_keep = 1  # the original user_prompt
    if head_keep + keep_tail >= len(messages):
        return messages  # already small enough

    older_msgs = messages[head_keep : len(messages) - keep_tail]
    recent_msgs = messages[len(messages) - keep_tail :]

    # Count read-only ops that fell inside the older window.
    cutoff_op_idx = _ops_seen_so_far(older_msgs, session.operations)
    older_ops = session.operations[:cutoff_op_idx]
    read_only_count = sum(1 for op in older_ops if op.op not in _MUTATION_OPS)

    pipeline_dict = session.pipeline_json.model_dump(by_alias=True)
    synopsis = _render_op_synopsis(
        older_ops, pipeline_dict, read_only_op_count=read_only_count,
    )

    if not synopsis:
        # Nothing useful to inject; bail and just truncate verbose results.
        return [_truncate_recent_msg(m) for m in messages]

    synopsis_msg = {
        "role": "assistant",
        "content": [{"type": "text", "text": synopsis}],
    }
    compressed = (
        [messages[0]] + [synopsis_msg] + [_truncate_recent_msg(m) for m in recent_msgs]
    )

    # Estimate savings for ops visibility
    before_chars = sum(len(json.dumps(m, default=str)) for m in messages)
    after_chars = sum(len(json.dumps(m, default=str)) for m in compressed)
    log.info(
        "compress_messages: %d msgs (%dch) → %d msgs (%dch), saved ~%d tokens",
        len(messages), before_chars, len(compressed), after_chars,
        max(0, (before_chars - after_chars) // 4),
    )
    return compressed


def _ops_seen_so_far(older_msgs: Iterable[dict[str, Any]], ops: list[Operation]) -> int:
    """Best-effort count of how many ops were taken before the recent window.

    Each tool_result message corresponds to one tool call (one operation).
    Count tool_result blocks among the older messages. Caps at len(ops).
    """
    count = 0
    for m in older_msgs:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                count += 1
    return min(count, len(ops))


def _truncate_recent_msg(msg: dict[str, Any]) -> dict[str, Any]:
    """For a retained recent message, trim verbose tool_result content."""
    if msg.get("role") != "user":
        return msg
    content = msg.get("content")
    if not isinstance(content, list):
        return msg
    new_blocks: list[Any] = []
    changed = False
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            new_blocks.append(block)
            continue
        body = block.get("content")
        if not isinstance(body, str):
            new_blocks.append(block)
            continue
        # We don't always know which tool emitted this result here, but we
        # can try the truncation anyway — _truncate_obj only mutates known
        # verbose shapes; unknown shapes pass through unchanged.
        for candidate in _VERBOSE_RESULT_OPS:
            new_body = _truncate_tool_result(candidate, body)
            if new_body != body:
                body = new_body
                changed = True
                break
        new_blocks.append({**block, "content": body})
    if not changed:
        return msg
    return {**msg, "content": new_blocks}
