"""Shadow Analyst Service — v15.3 Async Shadow Analysis.

Triggered after an MCP execution returns dataset (is_data_source: true).
Decision tree:
  P2:   Match user's agent_tools by keyword similarity
  P2.5: Reuse-First — call generic tools directly (no LLM needed)
        calc_statistics / find_outliers / correlation_analysis / distribution_test
  P3:   JIT — LLM generates compact Python → sandbox executes
        (only reached for non-numeric / edge-case datasets)

Streams SSE events: decision | stat_card | chart_card | done | error
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import sandbox_service
from app.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)

from app.prompts.catalog import SHADOW_ANALYST_SYSTEM as _ANALYSIS_SYSTEM

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
        self._llm = get_llm_client()

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

        # ── P2.5: Reuse-First — generic tools (no LLM needed) ─────────────────
        yield {
            "type": "decision",
            "method": "generic_tools",
            "message": "[Decision] 呼叫通用工具庫直接分析（Reuse-First）...",
        }
        cards_p25: List[Dict[str, Any]] = []
        chart_cards_p25: List[Dict[str, Any]] = []
        async for ev in self._run_generic_tools(raw_data, data_profile, mcp_name, row_count):
            if ev["type"] == "stat_card":
                cards_p25.append({k: v for k, v in ev.items() if k != "type"})
                yield ev
            elif ev["type"] == "chart_card":
                chart_cards_p25.append({k: v for k, v in ev.items() if k != "type"})
                yield ev
            else:
                yield ev

        if len(cards_p25) >= 2:
            # P2.5 produced enough cards — done
            return

        # ── P3: JIT fallback (only for non-numeric / exotic data) ─────────────
        yield {
            "type": "decision",
            "method": "jit",
            "message": "[Decision] 通用工具庫覆蓋不足，轉由自律工程師開發補充腳本...",
        }
        async for ev in self._run_jit(raw_data, data_profile, mcp_name, row_count):
            yield ev

    # ── P2.5 helper — generic tools direct call (no LLM) ──────────────────────

    async def _run_generic_tools(
        self,
        raw_data: List[Dict[str, Any]],
        data_profile: Dict[str, Any],
        mcp_name: str,
        row_count: int,
    ):
        """Call generic tools directly based on data profile. Yields stat_card / chart_card events."""
        from app.generic_tools.processing.statistical import (
            calc_statistics, find_outliers, distribution_test,
        )
        from app.generic_tools.processing.correlation import correlation_analysis
        from app.generic_tools.visualization.distribution import plot_box

        stats_meta = data_profile.get("stats", {})
        numeric_cols = list(stats_meta.keys())
        # primary column = first numeric column (prefer 'value')
        primary_col = next(
            (c for c in numeric_cols if c.lower() in ("value", "val", "measurement", "result")),
            numeric_cols[0] if numeric_cols else None,
        )

        if not primary_col:
            return  # no numeric data — fall through to P3

        # ── 1. calc_statistics ────────────────────────────────────────────────
        stats_result = calc_statistics(raw_data, column=primary_col)
        if stats_result["status"] == "success":
            p = stats_result["payload"]
            mean_val = p.get("mean", 0)
            std_val  = p.get("std", 0)
            cv_pct   = round(abs(std_val / mean_val) * 100, 2) if mean_val else 0.0
            skew     = p.get("skewness", 0)
            kurt     = p.get("kurtosis", 0)

            yield {"type": "stat_card", "label": f"CV ({primary_col})",
                   "value": cv_pct, "unit": "%",
                   "significance": "critical" if cv_pct > 30 else "warning" if cv_pct > 10 else "normal"}
            yield {"type": "stat_card", "label": "Skewness",
                   "value": round(skew, 3), "unit": "",
                   "significance": "warning" if abs(skew) > 1.0 else "normal"}
            yield {"type": "stat_card", "label": "Kurtosis",
                   "value": round(kurt, 3), "unit": "",
                   "significance": "warning" if abs(kurt) > 3.0 else "normal"}
            if row_count > 1:
                yield {"type": "stat_card", "label": f"Mean ({primary_col})",
                       "value": round(mean_val, 4), "unit": "",
                       "significance": "normal"}

        # ── 2. find_outliers ──────────────────────────────────────────────────
        if row_count >= 4:
            out_result = find_outliers(raw_data, column=primary_col, method="sigma")
            if out_result["status"] == "success":
                p = out_result["payload"]
                rate = p.get("outlier_rate_pct", 0)
                yield {"type": "stat_card", "label": "3σ Anomaly Rate",
                       "value": rate, "unit": "%",
                       "significance": "critical" if rate > 5 else "warning" if rate > 0 else "normal"}

        # ── 3. correlation_analysis (if 2+ numeric cols) ──────────────────────
        if len(numeric_cols) >= 2 and row_count >= 3:
            col_a, col_b = numeric_cols[0], numeric_cols[1]
            corr_result = correlation_analysis(raw_data, col_a=col_a, col_b=col_b)
            if corr_result["status"] == "success":
                p = corr_result["payload"]
                pearson = p.get("pearson_r", 0)
                yield {"type": "stat_card", "label": f"Pearson r ({col_a}↔{col_b})",
                       "value": round(pearson, 4), "unit": "",
                       "significance": "critical" if abs(pearson) > 0.7 else "warning" if abs(pearson) > 0.4 else "normal"}

        # ── 4. distribution_test (normality) ─────────────────────────────────
        if row_count >= 8:
            dist_result = distribution_test(raw_data, column=primary_col)
            if dist_result["status"] == "success":
                p = dist_result["payload"]
                is_normal = p.get("is_normal", True)
                jb = p.get("jb_statistic", 0)
                yield {"type": "stat_card", "label": "Distribution",
                       "value": "Normal" if is_normal else "Non-Normal",
                       "unit": f"JB={jb:.2f}", "significance": "normal" if is_normal else "warning"}

        # ── 5. Box plot via plot_box ──────────────────────────────────────────
        if row_count >= 4:
            # plot_box uses "columns" (plural) parameter, not "column"
            box_result = plot_box(raw_data, columns=[primary_col],
                                  title=f"{mcp_name} — {primary_col} Distribution")
            if box_result["status"] == "success" and box_result["payload"].get("plotly"):
                yield {"type": "chart_card",
                       "tool_name": "plot_box",
                       "summary": box_result["summary"],
                       "payload": box_result["payload"]}

        yield {
            "type": "done",
            "jit_code": None,
            "tool_used": "generic_tools",
            "intro": f"已使用通用工具庫分析「{mcp_name}」的 {primary_col} 欄位（{row_count} 筆）。",
        }

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
            resp = await self._llm.create(
                system=_ANALYSIS_SYSTEM,
                max_tokens=1500,
                messages=[{"role": "user", "content": user_msg}],
            )
            code = resp.text.strip()
            # Strip markdown fences if LLM added them
            code = re.sub(r"^```(?:python)?\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
        except Exception as exc:
            logger.error("Shadow JIT codegen failed: %s", exc)
            yield {"type": "error", "message": f"Code generation failed: {exc}"}
            return

        # Wrap flat analysis code in process() — sandbox requires process(raw_data)->dict.
        # The sandbox pre-injects `df` in global_ns so the inner code can still use `df`.
        sandbox_code = "def process(raw_data):\n"
        sandbox_code += "\n".join("    " + ln if ln.strip() else "" for ln in code.splitlines())
        sandbox_code += "\n    return result\n"

        # Execute in sandbox
        try:
            result = await sandbox_service.execute_script(script=sandbox_code, raw_data=raw_data)
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
            "jit_code": code,  # expose original unwrapped code to user
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
