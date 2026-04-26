"""self_critique node — verifies Agent answer integrity.

Two checks:
  1. Deterministic ID hallucination detection (regex, zero LLM cost)
  2. LLM-based value traceability check (calls LLM once)

Runs AFTER synthesis. If issues are found, amends the final_text.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

from python_ai_sidecar.agent_orchestrator_v2.helpers import (
    _detect_id_hallucinations,
    _extract_memory_citations,
)


# Phrases that signal the LLM is *aware* it couldn't complete the task
# and is suggesting next steps rather than asserting unverified data.
# These commonly appear when an ON_DUTY caller asks for an analysis that
# has no published skill — the LLM has nothing to call and rightly
# explains the limitation in plain text.
_LIMITATION_KEYWORDS = (
    "找不到",      # no skill found
    "無法直接",    # can't directly
    "沒有現成",    # no existing
    "聯繫 PE",     # contact PE
    "聯繫 IT_ADMIN",
    "聯繫 IT-ADMIN",
    "權限限制",    # permission limit
    "無權限",
    "目前無法",    # cannot currently
    "無法為您",
    "無法提供",
    "建議您聯繫",
    "建議聯絡",
    "請聯絡",
)


def _looks_like_self_aware_explanation(text: str) -> bool:
    """Detect a self-aware "I couldn't do this" response.

    Used by self_critique to skip the "all tool calls failed" amendment
    when the LLM has already explained the limitation gracefully — the
    amendment would otherwise overwrite a friendly answer with a generic
    error string, which is worse UX than leaving the original.
    """
    if not text:
        return False
    return any(kw in text for kw in _LIMITATION_KEYWORDS)


async def self_critique_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Stage 5: Self-Critique — verify every concrete value is traceable."""
    final_text = state.get("final_text", "")
    tools_used = state.get("tools_used", [])

    if not final_text or len(final_text) < 50:
        return {"reflection_result": {"pass": True}}

    # No tools used → potentially 100% hallucination, but also valid for
    # "I couldn't do this" self-aware responses (common when an ON_DUTY
    # caller asks for an analysis that has no published skill — there's
    # nothing to call, and the LLM correctly explains the limitation in
    # plain text). We only flag if the answer reads like asserted data.
    if not tools_used:
        if _looks_like_self_aware_explanation(final_text):
            return {"reflection_result": {"pass": True}}
        return {
            "reflection_result": {
                "pass": False,
                "issues": [{"text": "(所有工具呼叫均失敗)", "reason": "無任何成功的工具呼叫"}],
                "amended_text": "⚠️ 所有工具呼叫均未成功取得資料，無法提供分析。請補充必要的查詢參數後重試。",
            }
        }

    # 1. Deterministic: ID hallucination check
    hallucinated = _detect_id_hallucinations(final_text, tools_used)
    if hallucinated:
        logger.warning(
            "Self-Critique: detected %d hallucinated IDs: %s",
            len(hallucinated), hallucinated[:10],
        )
        amended = final_text
        for bad_id in hallucinated:
            amended = amended.replace(bad_id, f"{bad_id}⚠️[捏造]")
        return {
            "reflection_result": {
                "pass": False,
                "issues": [
                    {"text": bad_id, "reason": "ID 未在任何工具回傳中出現，疑為捏造"}
                    for bad_id in hallucinated
                ],
                "amended_text": (
                    amended
                    + "\n\n⚠️ Self-Critique 警告：以上標記的 ID（"
                    + ", ".join(hallucinated[:5])
                    + "）在本次工具回傳中找不到，可能是 AI 捏造。"
                ),
            }
        }

    # 2. LLM-based: value traceability check
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

    tools_summary = ", ".join(
        f"{t['tool']}({t['mcp_name']})" if t.get("mcp_name") else t["tool"]
        for t in tools_used
    ) if tools_used else "(無工具呼叫)"

    reflection_prompt = (
        "你是數據品質審查員。以下是 AI Agent 剛輸出的答案，以及本次對話中實際執行過的工具清單。\n\n"
        f"【已執行的工具】\n{tools_summary}\n\n"
        f"【Agent 答案】\n{final_text[:2000]}\n\n"
        "請逐句檢查答案中每個具體數值（感測器讀數、時間戳記、UCL/LCL、百分比、ID 等）：\n"
        "- 若數值可追溯到上方工具清單的回傳 → 標記 OK\n"
        "- 若數值無法追溯（可能是 LLM 推測/捏造）→ 標記 ISSUE，說明原因\n\n"
        "若全部 OK，回傳：{\"pass\": true}\n"
        "若有 ISSUE，回傳：{\"pass\": false, \"issues\": [{\"text\": \"問題句子\", \"reason\": \"原因\"}], "
        "\"amended_text\": \"修訂後答案（用[查無資料]替換無來源的數值）\"}\n"
        "只回傳 JSON，不要任何說明文字。"
    )

    try:
        llm = get_llm_client()
        import asyncio
        resp = await asyncio.wait_for(
            llm.create(
                system="你是數據品質審查員。",
                messages=[{"role": "user", "content": reflection_prompt}],
                max_tokens=800,
            ),
            timeout=12.0,
        )
        raw = (resp.text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        if not raw:
            return {"reflection_result": {"pass": True}}
        result = json.loads(raw)
        return {"reflection_result": result}
    except Exception as exc:
        logger.warning("Self-critique LLM reflection failed (non-blocking): %s", exc)
        return {"reflection_result": {"pass": True}}
