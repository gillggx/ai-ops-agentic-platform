"""Shadow Analyst Service — v15.2 Async Shadow Analysis.

Triggered after an MCP execution returns dataset (is_data_source: true).
Runs a focused statistical analysis (CV / Pearson / outliers / distribution)
using the v15.1 decision tree:
  P2: match user's agent_tools by keyword similarity
  P3: JIT — LLM generates compact Python → sandbox executes

Streams SSE events: decision | stat_card | done | error
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import sandbox_service

logger = logging.getLogger(__name__)

_settings = get_settings()
_MODEL = _settings.LLM_MODEL

_ANALYSIS_SYSTEM = """\
你是一位精確的統計分析工程師。
你的任務：給定數據 Profile，生成一段緊湊的 Python 分析腳本（不超過 60 行）。

規則：
1. 變數 `df`（pandas DataFrame）已預注入，直接使用
2. 只做唯讀操作（嚴禁 write / delete / to_csv / to_sql）
3. 必須計算至少 2 個統計指標（CV / Pearson R / P-value / 峰度 / 偏態 / 異常率）
4. 最後一行必須是：result = {"stat_cards": [...], "intro": "..."}

stat_card 格式（每張卡）：
{"label": "CV (pressure)", "value": 12.3, "unit": "%", "significance": "normal|warning|critical", "note": "可選說明"}

significance 規則：
- CV > 30% 或 |Pearson R| > 0.7（強相關）→ "critical"
- CV 10-30% 或 |Pearson R| 0.4-0.7 → "warning"
- 其他 → "normal"

只輸出 Python 代碼，不加說明文字，不加 markdown 代碼塊。"""

_ANALYSIS_USER_TMPL = """\
MCP 名稱：{mcp_name}
資料筆數：{row_count}

DataProfile：
{profile_text}

請生成分析腳本。"""


def _profile_to_text(profile: Dict[str, Any]) -> str:
    """Convert DataProfile dict to compact text for LLM prompt."""
    lines = []
    meta = profile.get("meta", {})
    stats = profile.get("stats", {})
    samples = profile.get("samples", [])

    if meta:
        lines.append("欄位資訊：")
        for col, info in meta.items():
            lines.append(
                f"  - {col}: type={info.get('dtype','?')}, "
                f"null={info.get('null_count',0)}, "
                f"unique={info.get('unique_count','?')}"
            )

    if stats:
        lines.append("數值統計：")
        for col, s in stats.items():
            lines.append(
                f"  - {col}: min={s.get('min')}, max={s.get('max')}, "
                f"mean={s.get('mean')}, std={s.get('std')}"
            )

    if samples:
        lines.append(f"前 {len(samples)} 筆樣本（部分欄位）：")
        for row in samples[:3]:
            lines.append(f"  {row}")

    return "\n".join(lines) if lines else "(無 Profile 資訊)"


def _keyword_match(description: str, mcp_name: str, columns: List[str]) -> float:
    """Simple keyword similarity score between 0-1 for agent_tool matching."""
    tokens = set(
        re.split(r"[\s_\-/,，]+", (description + " " + mcp_name).lower())
    )
    col_tokens = set(c.lower() for c in columns)
    overlap = tokens & col_tokens
    if not tokens:
        return 0.0
    return len(overlap) / len(tokens)


class ShadowAnalystService:
    """Async shadow analysis for a dataset returned by an MCP tool."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._client = anthropic.AsyncAnthropic(api_key=_settings.ANTHROPIC_API_KEY)

    async def analyze(
        self,
        raw_data: List[Dict[str, Any]],
        data_profile: Dict[str, Any],
        mcp_name: str,
        agent_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Main entry — yields SSE-compatible dicts."""
        columns = list(data_profile.get("meta", {}).keys())
        row_count = data_profile.get("row_count", len(raw_data) if isinstance(raw_data, list) else 0)

        # ── P2: match agent_tools ─────────────────────────────────────────────
        best_tool: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for t in (agent_tools or []):
            score = _keyword_match(
                t.get("description", "") + " " + t.get("name", ""),
                mcp_name,
                columns,
            )
            if score > best_score:
                best_score = score
                best_tool = t

        if best_tool and best_score >= 0.3:
            yield {
                "type": "decision",
                "method": "agent_tool",
                "message": f"[Decision] 找到匹配工具「{best_tool['name']}」(score={best_score:.2f})，套用私有工具...",
            }
            async for ev in self._run_agent_tool(best_tool, raw_data):
                yield ev
            return

        # ── P3: JIT ────────────────────────────────────────────────────────────
        yield {
            "type": "decision",
            "method": "jit",
            "message": "[Decision] 精準匹配失敗，轉由自律工程師開發專屬腳本...",
        }
        async for ev in self._run_jit(raw_data, data_profile, mcp_name, row_count):
            yield ev

    # ── P2 helper ─────────────────────────────────────────────────────────────

    async def _run_agent_tool(
        self,
        tool: Dict[str, Any],
        raw_data: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            result = await sandbox_service.execute_script(
                script=tool.get("code", ""),
                raw_data=raw_data,
            )
            cards = self._extract_cards(result)
            for card in cards:
                yield {"type": "stat_card", **card}
            yield {
                "type": "done",
                "jit_code": None,
                "tool_used": tool.get("name", "agent_tool"),
                "intro": f"我套用了私有工具「{tool.get('name','')}」進行分析。",
            }
        except Exception as exc:
            logger.warning("shadow agent_tool execution failed: %s", exc)
            yield {"type": "error", "message": str(exc)}

    # ── P3 helper ─────────────────────────────────────────────────────────────

    async def _run_jit(
        self,
        raw_data: List[Dict[str, Any]],
        data_profile: Dict[str, Any],
        mcp_name: str,
        row_count: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # Generate code via LLM
        profile_text = _profile_to_text(data_profile)
        user_msg = _ANALYSIS_USER_TMPL.format(
            mcp_name=mcp_name,
            row_count=row_count,
            profile_text=profile_text,
        )
        try:
            resp = await self._client.messages.create(
                model=_MODEL,
                max_tokens=800,
                system=_ANALYSIS_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            code = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    code = block.text.strip()
                    break
            # Strip markdown fences if LLM added them
            code = re.sub(r"^```(?:python)?\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
        except Exception as exc:
            logger.error("Shadow JIT codegen failed: %s", exc)
            yield {"type": "error", "message": f"Code generation failed: {exc}"}
            return

        # Execute in sandbox
        try:
            result = await sandbox_service.execute_script(script=code, raw_data=raw_data)
        except Exception as exc:
            logger.warning("Shadow JIT sandbox failed: %s", exc)
            yield {"type": "error", "message": f"Sandbox execution failed: {exc}"}
            return

        cards = self._extract_cards(result)
        if not cards:
            # Fallback: create a single info card from raw result
            cards = [{"label": "分析結果", "value": str(result)[:60], "unit": "", "significance": "normal"}]

        for card in cards:
            yield {"type": "stat_card", **card}

        intro = "我自發執行了統計分析，發現以下結果："
        if isinstance(result, dict) and result.get("intro"):
            intro = result["intro"]

        yield {
            "type": "done",
            "jit_code": code,
            "tool_used": "jit",
            "intro": intro,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_cards(result: Any) -> List[Dict[str, Any]]:
        """Extract stat_cards from sandbox result (various shapes)."""
        if isinstance(result, dict):
            cards = result.get("stat_cards") or result.get("cards")
            if isinstance(cards, list):
                return [c for c in cards if isinstance(c, dict)]
            # Flatten simple k:v result into cards
            cards = []
            for k, v in result.items():
                if k in ("stat_cards", "cards", "intro"):
                    continue
                if isinstance(v, (int, float)):
                    cards.append({"label": str(k), "value": round(float(v), 4), "unit": "", "significance": "normal"})
            return cards
        return []
