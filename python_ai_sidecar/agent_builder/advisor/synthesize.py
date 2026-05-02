"""Node 4 — synthesize the final markdown answer given the data fetched
by Node 3 (block records from Java). The LLM does NOT call tools and
does NOT fetch anything; its only job is to write a clear, opinionated
explanation in the user's language.

Each function returns a markdown string. Length-bounded so the panel
doesn't blow up vertically.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


_MAX_OUTPUT_TOKENS = 900


def _trim_block(b: dict[str, Any]) -> dict[str, Any]:
    """Keep only the LLM-relevant fields. Bigger schemas are truncated to
    keep prompts cheap; the user sees the full schema in BlockDocsDrawer
    anyway, this is just for the agent's writing context."""
    out: dict[str, Any] = {
        "name": b.get("name"),
        "category": b.get("category"),
        "description": b.get("description"),
        "param_schema": b.get("param_schema"),
        "input_schema": b.get("input_schema"),
        "output_schema": b.get("output_schema"),
    }
    examples = b.get("examples")
    if isinstance(examples, list) and examples:
        out["examples_first_two"] = examples[:2]
    elif isinstance(examples, dict):
        out["examples"] = examples
    return out


# ── EXPLAIN ───────────────────────────────────────────────────────────

_EXPLAIN_SYSTEM = """You are a Pipeline Builder assistant explaining ONE block
to a manufacturing engineer. Be concrete, opinionated, and brief.

Format the answer in markdown:
  ## {block_name}
  **用途**：1-2 句白話
  **何時用**：bullet list, 2-3 點
  **參數**：每個重要 param 一行 (`name` — type — what it controls)
  **輸入/輸出**：DataFrame schema 簡述
  **範例**：1 行最常見呼叫場景

Rules:
- Source-of-truth = the JSON I give you. Don't invent params or behaviour.
- If a field is empty in the JSON, omit that section silently.
- Reply in the user's language (Chinese if user wrote Chinese, else English).
- ≤ 250 words total.
"""


async def synthesize_explain(user_question: str, block: dict[str, Any]) -> str:
    """Produce the markdown explanation for one block."""
    client = get_llm_client()
    payload = {
        "user_question": user_question,
        "block_record": _trim_block(block),
    }
    try:
        resp = await client.create(
            system=_EXPLAIN_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
        return (resp.text or "").strip() or _fallback_explain(block)
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.synthesize_explain failed (%s) — fallback", e)
        return _fallback_explain(block)


def _fallback_explain(block: dict[str, Any]) -> str:
    """Last-resort plain dump from the block record. Used when LLM fails.
    Keeps the user from seeing a blank panel."""
    name = block.get("name", "(unknown)")
    desc = block.get("description") or "(no description)"
    return f"## {name}\n\n{desc}\n\n_(LLM 摘要失敗，這是 description 原文)_"


# ── COMPARE ──────────────────────────────────────────────────────────

_COMPARE_SYSTEM = """You are comparing 2-5 Pipeline Builder blocks for a
manufacturing engineer trying to choose between them.

Format:
  ## 對比：A vs B (vs C ...)
  **共同點**：1-2 句
  **差異**：markdown table —
    | 維度 | A | B | ... |
    | 用途 | ... | ... |
    | 輸入 shape | ... |
    | 何時用 |  ... |
  **建議**：1-2 句決策提示（例：「想看趨勢用 A；想看分布用 B」）

Rules:
- Source-of-truth = JSON. Don't invent.
- Reply in user's language.
- ≤ 350 words. Table ≤ 4 rows.
"""


async def synthesize_compare(user_question: str, blocks: list[dict[str, Any]]) -> str:
    client = get_llm_client()
    payload = {
        "user_question": user_question,
        "blocks": [_trim_block(b) for b in blocks],
    }
    try:
        resp = await client.create(
            system=_COMPARE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
        return (resp.text or "").strip() or _fallback_compare(blocks)
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.synthesize_compare failed (%s) — fallback", e)
        return _fallback_compare(blocks)


def _fallback_compare(blocks: list[dict[str, Any]]) -> str:
    lines = ["## 對比 (LLM 摘要失敗，原始 description)\n"]
    for b in blocks:
        lines.append(f"### {b.get('name')}\n{b.get('description') or '(no description)'}\n")
    return "\n".join(lines)


# ── RECOMMEND ────────────────────────────────────────────────────────

_RECOMMEND_SYSTEM = """You are recommending Pipeline Builder blocks to a
manufacturing engineer based on their use case.

Format:
  ## 推薦：{intent summary}

  ### 1. block_xxx — 最推薦
  **why**: 1-2 句解釋為何適合這個 use case
  **next steps**: 接哪一個 block / 設什麼 param

  ### 2. block_yyy — 次選
  ...

  ### 3. block_zzz — 看情況
  ...（最多 3 個）

Rules:
- Source-of-truth = the candidate list I give you (already keyword-matched).
- Don't recommend blocks NOT in the candidate list.
- If the candidate list is empty, say so honestly + suggest the user
  describe the use case differently.
- Reply in user's language.
- ≤ 350 words.
"""


async def synthesize_recommend(
    user_question: str, intent_summary: str, candidates: list[dict[str, Any]]
) -> str:
    client = get_llm_client()
    payload = {
        "user_question": user_question,
        "intent_summary": intent_summary,
        "candidates": [_trim_block(b) for b in candidates],
    }
    try:
        resp = await client.create(
            system=_RECOMMEND_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
        return (resp.text or "").strip() or _fallback_recommend(candidates)
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.synthesize_recommend failed (%s) — fallback", e)
        return _fallback_recommend(candidates)


def _fallback_recommend(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "找不到符合的 block。能否換個方式描述需求？"
    lines = ["## 推薦 (LLM 摘要失敗，原始 candidate list)\n"]
    for b in candidates[:3]:
        lines.append(f"### {b.get('name')}\n{b.get('description') or '(no description)'}\n")
    return "\n".join(lines)
