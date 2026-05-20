"""Tool-using doc Q&A agent (v6.2, 2026-05-20).

Anthropic tool-use loop with 3 read-only doc tools:
  - list_blocks(category?)         list block headlines, optional category filter
  - search_blocks_by_keyword(kw)   substring match across name + description + tags
  - inspect_block_doc(block_id)    fetch full Markdown body (admin-edited DB doc
                                    preferred; falls back to seed description)

Round cap = 5. Tools are read-only so there's no canvas-mutation risk;
the cap exists purely to bound token spend on pathological loops.

Stream contract matches the legacy advisor: emits StreamEvent of type
`advisor_progress` for intermediate tool calls (so frontend can show
"looking up block_X..." chips) and a final `advisor_answer` with the
synthesized markdown.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from python_ai_sidecar.agent_builder.session import StreamEvent
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.clients.java_client import JavaAPIClient


logger = logging.getLogger(__name__)


MAX_ROUNDS = 5
MAX_TOKENS_PER_ROUND = 2048
KEYWORD_SEARCH_TOP_K = 6


_SYSTEM = """你是 pipeline-builder 的 block 使用 Q&A 助手。User 問 block 怎麼用 /
哪個 block 適合 / 兩個 block 差在哪。你**主動 query** 工具拿 docs 再回答，
不要憑記憶。

可用工具:
  - list_blocks(category?)          當 user 提到類別 (source / transform / chart /
                                    check / output / logic) 時用
  - search_blocks_by_keyword(kw)    根據 user 意圖找候選 block (e.g. "OOC"、
                                    "drift"、"unnest")
  - inspect_block_doc(block_id)     拿完整 Markdown doc (含 When to invoke /
                                    不適用情境 / Inputs/Outputs / Examples)

決策原則:
  1. user 提到 specific block name → 直接 inspect_block_doc 該 block
  2. user 講意圖 / keyword → search_blocks_by_keyword 找候選 → 再 inspect 1-2 個
  3. 比較問題 → inspect_block_doc 各別拿 doc，並列回答
  4. 推薦問題 → search → inspect top 2-3 → 比較後給推薦
  5. 拿到 doc 後**直接回答**，不要再無謂 inspect

回答格式 (Markdown):
  - 簡明 2-5 段
  - 若涉及 params 用 table
  - 若有 example chain 用 code block
  - 結尾不要客套，user 是 engineer

避免:
  - 不要 list 全 catalog (太長)
  - 不要重複 inspect 同 block
  - 不要憑空寫 params (一定要從 inspect 結果抄)
"""


# ── Tool specs (Anthropic format) ──────────────────────────────────────


_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_blocks",
        "description": (
            "List blocks in the catalog. Returns name + category + 1-line "
            "description per block. Use when the user asks about a category "
            "(e.g. 'chart blocks 有哪些')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional: source / transform / check / chart / output / logic",
                }
            },
        },
    },
    {
        "name": "search_blocks_by_keyword",
        "description": (
            "Find blocks whose name / description / category contains the keyword. "
            "Returns top-6 matches with name + 1-line description. Use when user "
            "describes an intent (e.g. 'count OOC', 'detect drift')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Single keyword or short phrase"}
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "inspect_block_doc",
        "description": (
            "Fetch full Markdown doc for one block (admin-edited if available, "
            "else seed description). Includes When to invoke / 不適用情境 / "
            "Inputs / Outputs / Parameters / Examples sections. Use this once "
            "you've identified a candidate block to actually answer the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"block_id": {"type": "string"}},
            "required": ["block_id"],
        },
    },
]


# ── Tool dispatchers ───────────────────────────────────────────────────


async def _exec_list_blocks(args: dict, java: JavaAPIClient) -> str:
    category = (args.get("category") or "").strip() or None
    blocks = await java.list_blocks(category=category)
    if not blocks:
        return "(no blocks found)"
    lines = [
        f"- {b.get('name')}  [{b.get('category','?')}]  {_short_desc(b)}"
        for b in blocks[:30]
    ]
    return "\n".join(lines) + (f"\n... ({len(blocks)} total)" if len(blocks) > 30 else "")


async def _exec_search(args: dict, java: JavaAPIClient) -> str:
    kw = (args.get("keyword") or "").strip().lower()
    if not kw:
        return "(empty keyword)"
    all_blocks = await java.list_blocks()
    scored: list[tuple[int, dict]] = []
    for b in all_blocks:
        haystack = " ".join(
            str(b.get(f) or "").lower()
            for f in ("name", "description", "category", "tags")
        )
        score = haystack.count(kw)
        if score > 0:
            scored.append((score, b))
    scored.sort(key=lambda t: -t[0])
    top = scored[:KEYWORD_SEARCH_TOP_K]
    if not top:
        return f"(no blocks match keyword '{kw}')"
    lines = [
        f"- {b.get('name')}  [{b.get('category','?')}]  score={s}  {_short_desc(b)}"
        for s, b in top
    ]
    return "\n".join(lines)


async def _exec_inspect_block_doc(args: dict, java: JavaAPIClient) -> str:
    block_id = (args.get("block_id") or "").strip()
    if not block_id:
        return "(block_id required)"

    # 1. Pull rich Markdown from block_docs (admin-edited).
    doc = await java.get_block_doc(block_id, "1.0.0")
    if doc and doc.get("markdown"):
        return doc["markdown"]

    # 2. Fall back to seed description from block_definitions.
    block = await java.get_block_by_name(block_id)
    if block is None:
        return f"(block '{block_id}' not found in catalog)"
    desc = block.get("description") or "(no description in seed)"
    params = block.get("param_schema") or {}
    examples = block.get("examples") or []
    body = (
        f"# {block_id}\n\n"
        f"{desc}\n\n"
        f"## Parameters (raw schema)\n"
        f"```json\n{json.dumps(params, ensure_ascii=False, indent=2)[:1500]}\n```\n"
    )
    if examples:
        body += "\n## Examples (raw)\n"
        for ex in examples[:2]:
            body += f"- {ex.get('label','?')}: {json.dumps(ex.get('params', {}), ensure_ascii=False)[:200]}\n"
    return body


_DISPATCH = {
    "list_blocks": _exec_list_blocks,
    "search_blocks_by_keyword": _exec_search,
    "inspect_block_doc": _exec_inspect_block_doc,
}


def _short_desc(block: dict) -> str:
    raw = (block.get("description") or "").strip()
    first_line = raw.split("\n", 1)[0]
    return first_line[:100] + ("…" if len(first_line) > 100 else "")


# ── Helpers: extract Anthropic response content ────────────────────────


def _extract_text(resp: Any) -> str:
    content = getattr(resp, "content", None) or []
    parts: list[str] = []
    for blk in content:
        btype = getattr(blk, "type", None) or (blk.get("type") if isinstance(blk, dict) else None)
        if btype == "text":
            t = getattr(blk, "text", None) or (blk.get("text") if isinstance(blk, dict) else "")
            if t:
                parts.append(str(t))
    return "\n\n".join(parts).strip()


def _extract_tool_calls(resp: Any) -> list[dict]:
    content = getattr(resp, "content", None) or []
    out: list[dict] = []
    for blk in content:
        btype = getattr(blk, "type", None) or (blk.get("type") if isinstance(blk, dict) else None)
        if btype != "tool_use":
            continue
        name = getattr(blk, "name", None) or (blk.get("name") if isinstance(blk, dict) else None)
        args = getattr(blk, "input", None) or (blk.get("input") if isinstance(blk, dict) else None) or {}
        tu_id = getattr(blk, "id", None) or (blk.get("id") if isinstance(blk, dict) else None)
        if name and tu_id:
            out.append({"name": name, "args": dict(args) if isinstance(args, dict) else {}, "id": tu_id})
    return out


def _assistant_message(resp: Any) -> dict:
    """Serialize Anthropic response into messages-history dict shape."""
    content = getattr(resp, "content", None) or []
    parts: list[dict] = []
    for blk in content:
        btype = getattr(blk, "type", None) or (blk.get("type") if isinstance(blk, dict) else None)
        if btype == "text":
            t = getattr(blk, "text", None) or (blk.get("text") if isinstance(blk, dict) else "")
            if t:
                parts.append({"type": "text", "text": str(t)})
        elif btype == "tool_use":
            name = getattr(blk, "name", None) or (blk.get("name") if isinstance(blk, dict) else None)
            args = getattr(blk, "input", None) or (blk.get("input") if isinstance(blk, dict) else None) or {}
            tu_id = getattr(blk, "id", None) or (blk.get("id") if isinstance(blk, dict) else None)
            if name and tu_id:
                parts.append({"type": "tool_use", "id": tu_id, "name": name,
                              "input": args if isinstance(args, dict) else {}})
    return {"role": "assistant", "content": parts}


# ── Main loop ──────────────────────────────────────────────────────────


async def stream_doc_qa_agent(
    user_message: str,
    *,
    java: JavaAPIClient,
) -> AsyncGenerator[StreamEvent, None]:
    """Tool-using Q&A loop. Yields:
      - 0..N `advisor_progress` events (per tool call, for UI chips)
      - 1 `advisor_answer` event with final markdown
      - 1 `done` event
    """
    client = get_llm_client()
    messages: list[dict] = [{"role": "user", "content": user_message}]
    final_text = ""

    for round_n in range(MAX_ROUNDS):
        try:
            resp = await client.create(
                system=_SYSTEM,
                messages=messages,
                tools=_TOOL_SPECS,
                max_tokens=MAX_TOKENS_PER_ROUND,
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning("doc_qa: LLM call failed round %d: %s", round_n, ex)
            yield StreamEvent(
                type="advisor_answer",
                data={"kind": "error", "markdown": f"LLM call failed: {ex}"[:300]},
            )
            yield StreamEvent(type="done", data={"status": "advisor_done"})
            return

        tool_calls = _extract_tool_calls(resp)
        text = _extract_text(resp)
        if text:
            final_text = text  # keep latest text as the answer-in-progress

        if not tool_calls:
            # LLM emitted only text — we're done
            break

        # Append assistant message (with tool_use blocks) — required by Anthropic
        messages.append(_assistant_message(resp))

        # Execute tools, append tool_result blocks in next user message
        tool_results: list[dict] = []
        for call in tool_calls:
            name = call["name"]
            args = call["args"]
            tu_id = call["id"]
            yield StreamEvent(
                type="advisor_progress",
                data={
                    "round": round_n + 1,
                    "tool": name,
                    "args": args,
                },
            )
            fn = _DISPATCH.get(name)
            if fn is None:
                result_text = f"(unknown tool: {name})"
            else:
                try:
                    result_text = await fn(args, java)
                except Exception as ex:  # noqa: BLE001
                    logger.warning("doc_qa: tool %s threw: %s", name, ex)
                    result_text = f"(tool error: {ex})"[:500]
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": result_text,
            })
        messages.append({"role": "user", "content": tool_results})

    if not final_text:
        final_text = "(LLM produced no answer — try rephrasing the question)"

    yield StreamEvent(
        type="advisor_answer",
        data={"kind": "explain", "markdown": final_text},
    )
    yield StreamEvent(type="done", data={"status": "advisor_done"})
