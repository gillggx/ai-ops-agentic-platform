"""v30.18 (2026-05-18) — Task contract extractor.

Runs once per build, right after plan is confirmed. Extracts a structured
task contract from the user instruction so the per-block verifier
(_judge_task_progress) can check task accomplishment instead of just
quantifier semantic match.

Failure-mode: extractor errors → leave state.v30_task_contract=None;
phase_verifier falls back to the older _llm_judge_phase_outcome path.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState

logger = logging.getLogger(__name__)


_SYSTEM = """你是 pipeline task contract extractor。從 user instruction 抽出**結構化**任務 spec。

輸出 JSON (no markdown fence)，schema:
{
  "user_instruction": str,         # 原 user 原話 (照搬，不縮)
  "primary_action": str,           # 一句短語，e.g. "show trend chart" / "check ooc threshold" / "list process records"
  "source_filters": dict,          # 限制 raw_data 範圍: {"toolID": "EQP-01", "step": "STEP_001", "time_range": "7d"}
  "data_filters": dict,            # 對 nested 資料的二次篩選: {"chart_name": "xbar_chart"}
  "output_kind": str,              # 最終呈現格式: "line chart" / "table" / "verdict + chart" / "scalar verdict" / ...
  "markers": [str],                # 圖上要的標記 (UCL / LCL / OOC / spec line / ...), 沒提就 []
  "count_target": int | null,      # user 明確寫的筆數 (e.g. "最近 100 筆" → 100; 沒寫 → null)
  "count_strictness": "strict" | "flexible" | "none"
    # strict: user 寫精確數量且要嚴格達到 (e.g. "正好 5 次")
    # flexible: user 寫數量但有 20% 緩衝 (e.g. "最近 100 筆")
    # none: user 沒提數量
}

規則:
1. 只抽 user **明說**的；沒提的 field 留空 dict / 空 list / null
2. primary_action 用動詞短語，不要寫長句
3. source_filters 是「資料源層面」的篩選 (機台 / 站點 / 時間)
4. data_filters 是「資料內部 nested 結構」的篩選 (chart_name / param_name / status='OOC')
5. 若 user 寫了「xbar_chart」「r_chart」這種 chart_name → data_filters.chart_name 必填
6. 若 user 寫了「APC param X」「recipe Y」→ data_filters.param_name / recipe 必填
7. 不要從 phase.goal 抽（那是 planner 二手轉述）；以 user_instruction 原話為準
"""


def _extract_first_json(text: str) -> str:
    """Return first balanced JSON object substring, else text unchanged."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


async def task_contract_extractor_node(state: BuildGraphState) -> dict[str, Any]:
    """Extract task_contract from instruction. Returns state delta."""
    instruction = (state.get("instruction") or "").strip()
    if not instruction or not state.get("v30_phases"):
        # No instruction or not on v30 path — skip
        return {}

    # Don't re-extract if already cached (e.g. resumed session)
    if state.get("v30_task_contract"):
        return {}

    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
    client = get_llm_client()

    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": f"USER INSTRUCTION:\n{instruction[:1500]}"}],
            max_tokens=600,
        )
        raw = (resp.text or "").strip()
        body = _extract_first_json(raw)
        contract = json.loads(body)
    except Exception as ex:  # noqa: BLE001 — extractor failure must not block build
        logger.warning("task_contract_extractor: extraction failed (%s) — fallback to no contract", ex)
        return {"v30_task_contract": None}

    if not isinstance(contract, dict):
        logger.warning("task_contract_extractor: parsed contract is not dict (%s)", type(contract))
        return {"v30_task_contract": None}

    # Minimal validation — ensure key fields exist (use {}/[]/None defaults)
    contract.setdefault("user_instruction", instruction)
    contract.setdefault("primary_action", "")
    contract.setdefault("source_filters", {})
    contract.setdefault("data_filters", {})
    contract.setdefault("output_kind", "")
    contract.setdefault("markers", [])
    contract.setdefault("count_target", None)
    contract.setdefault("count_strictness", "none")

    logger.info(
        "task_contract_extractor: extracted contract primary_action=%r data_filters=%s count_target=%s",
        contract.get("primary_action"),
        contract.get("data_filters"),
        contract.get("count_target"),
    )

    return {"v30_task_contract": contract}
