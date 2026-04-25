"""LLM-based abstraction of raw agent interactions into reusable memory.

Phase 1 of the Agentic Memory System.

Core idea: raw "success patterns" like
    execute_mcp(X) → execute_jit(Y) → execute_skill(Z)
are brittle because tool names drift. Instead, abstract each successful
interaction into a (intent, action) pair:

    intent  = "When the user asks for X-type information"
    action  = "Use Y method, avoiding Z pitfall"

These abstractions survive tool renaming/refactoring and carry the
lesson rather than the trace.

Design:
  - Input:  user_query, agent_final_text, tool_chain summary
  - Output: {intent_summary, abstract_action}  or  None (not worth saving)
  - Zero side effects — caller decides what to do with the output
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_ABSTRACTION_SYSTEM_PROMPT = """你是 AI Agent 的自我反思模組。給你一次剛完成的成功任務紀錄，
你的任務是把它萃取成「可重複使用的抽象經驗」，而不是「這次用了什麼工具」。

【核心原則】
1. intent_summary：描述「當使用者問什麼類型的問題時」（泛化的觸發條件）
2. abstract_action：描述「該採取什麼策略」（抽象的行動要領，不記具體工具名稱）
3. 如果這次任務的「教訓」是「不要做什麼」（例如避免某種錯誤模式），一定要寫進去
4. 如果這次任務太瑣碎、太具體、或沒有可泛化的價值 → 回傳 null

【正面範例】
raw: 使用者問「最近機台表現」，Agent 呼叫 list_recent_events(since=7d) → execute_jit 聚合
good:
  intent: "當使用者詢問機台表現統計、OOC 排行、跨機台比較時"
  action: "優先用 list_recent_events 帶適當時間窗 (7d/24h) 取得完整樣本，再用 execute_jit 寫 python 聚合。不要逐筆查 get_process_context 來統計。"

raw: 使用者問「看 SPC chart」，Agent 呼叫 execute_skill(SPC 管制圖呈現)
good:
  intent: "當使用者明確要求查看標準 SPC 管制圖（xbar/p/s/c chart）時"
  action: "優先找 <skill_catalog> 中的 'SPC 管制圖呈現' skill，用 execute_skill 一次呼叫完成，不要自己用 execute_jit 組圖。"

【負面範例 — 不值得寫】
raw: 使用者說「你好」，Agent 回覆「你好」
→ 太瑣碎，回傳 null

raw: 使用者問一個具體 lot 的狀態
→ 太具體（某一個 lot），無法泛化，回傳 null

【輸出格式 — 嚴格 JSON，不要 markdown fence】
成功萃取：
{"intent_summary": "...", "abstract_action": "..."}

不值得保存：
null
"""


def _parse_abstraction_response(raw: str) -> Optional[Dict[str, str]]:
    """Parse LLM output → {intent_summary, abstract_action} or None."""
    if not raw:
        return None
    text = raw.strip()
    # Strip markdown fences if LLM added them despite instructions
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

    # "null" → not worth saving
    if text.lower() in ("null", "none", '"null"'):
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Memory abstraction: LLM returned invalid JSON: %r", text[:200])
        return None

    if not isinstance(data, dict):
        return None

    intent = data.get("intent_summary", "").strip()
    action = data.get("abstract_action", "").strip()
    if not intent or not action:
        return None
    return {"intent_summary": intent, "abstract_action": action}


def _build_abstraction_prompt(
    user_query: str,
    agent_final_text: str,
    tool_chain: List[Dict[str, Any]],
) -> str:
    """Compose the user message for the abstraction LLM call.

    Keeps the prompt compact — we only need the decision trace, not the
    full tool results.
    """
    tool_summary_lines = []
    for t in tool_chain[:10]:  # cap at 10 to keep prompt lean
        name = t.get("tool", "?")
        mcp_name = t.get("mcp_name") or ""
        params = t.get("params") or {}
        params_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])
        if mcp_name:
            tool_summary_lines.append(f"  - {name}({mcp_name}) params: {params_str}")
        else:
            tool_summary_lines.append(f"  - {name} params: {params_str}")
    tool_str = "\n".join(tool_summary_lines) if tool_summary_lines else "  (none)"

    return (
        f"【使用者原始問題】\n{user_query[:500]}\n\n"
        f"【Agent 執行的工具鏈】\n{tool_str}\n\n"
        f"【Agent 最終回答（前 800 字）】\n{agent_final_text[:800]}\n\n"
        "請萃取這次經驗的抽象 (intent_summary + abstract_action)，"
        "或回傳 null 若不值得保存。只輸出 JSON。"
    )


async def abstract_memory(
    llm_client: Any,
    user_query: str,
    agent_final_text: str,
    tool_chain: List[Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    """Call LLM to abstract a successful agent interaction into a memory.

    Args:
        llm_client: object with async create(system, messages, max_tokens) method
                    (either AnthropicLLMClient or OllamaLLMClient from llm_client.py)
        user_query: the original user message
        agent_final_text: Agent's synthesis text
        tool_chain: list of {tool, mcp_name, params} dicts from _tools_used

    Returns:
        {"intent_summary": str, "abstract_action": str}  or  None
    """
    # Skip obviously-not-worth-it cases without spending LLM tokens
    if not user_query or not agent_final_text:
        return None
    if len(agent_final_text) < 50:
        return None  # too short, likely a greeting or error
    if not tool_chain:
        return None  # no actual work done

    user_content = _build_abstraction_prompt(user_query, agent_final_text, tool_chain)

    try:
        resp = await llm_client.create(
            system=_ABSTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("Memory abstraction: LLM call failed — %s", exc)
        return None

    raw_text = getattr(resp, "text", "") or ""
    result = _parse_abstraction_response(raw_text)
    if result is None:
        logger.debug("Memory abstraction: not worth saving (user_query=%r)", user_query[:60])
    else:
        logger.info(
            "Memory abstraction OK: intent=%r",
            result["intent_summary"][:60],
        )
    return result
