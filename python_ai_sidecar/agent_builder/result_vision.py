"""result_vision (2026-07-13) — build 完工前的成品目檢。

user 裁決（成品目檢 spec）：
  Q1 chart 與 table 都以「截圖」提供給 LLM（統一、可控）；
  Q2 judge 不過 → builder 自動修 1 輪，仍不過 → 失敗卡帶 judge 指導；
  Q3 開關預設 ON（RESULT_VISION_CHECK=0 關閉 → 只剩 deterministic 規格檢）；
  Q4 渲染 = headless Chromium（Playwright，open source）跑「跟使用者看到
     一模一樣」的前端 SVG 引擎 — tools/result_render/（bundle 進 repo）。

失敗哲學：整條鏈 fail-open — 渲染掛 / vision 掛 / JSON 壞都回 None
（= 跳過目檢，不擋 build），只留 log。目檢是把關不是單點故障源。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("python_ai_sidecar.agent_builder.result_vision")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RENDER_DIR = _REPO_ROOT / "tools" / "result_render"
_RENDER_TIMEOUT_SEC = 45
_JUDGE_MODEL = os.environ.get("RESULT_VISION_MODEL", "claude-haiku-4-5-20251001")


def is_result_vision_enabled() -> bool:
    return os.environ.get("RESULT_VISION_CHECK", "1").strip() not in ("0", "false", "off")


def render_result_png(payload: dict[str, Any]) -> bytes | None:
    """headless 渲染成品 → PNG bytes；任何失敗回 None（fail-open）。"""
    node = shutil.which("node") or "/usr/bin/node"
    script = _RENDER_DIR / "render.mjs"
    if not script.exists():
        logger.warning("result_vision: render.mjs missing at %s — skip", script)
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="rv-") as td:
            in_path = Path(td) / "payload.json"
            out_path = Path(td) / "out.png"
            in_path.write_text(json.dumps(payload, ensure_ascii=False, default=str))
            proc = subprocess.run(
                [node, str(script), str(in_path), str(out_path)],
                capture_output=True, text=True, timeout=_RENDER_TIMEOUT_SEC,
                cwd=str(_RENDER_DIR),
            )
            if proc.returncode != 0 or not out_path.exists():
                logger.warning("result_vision: render failed rc=%s err=%s",
                               proc.returncode, (proc.stderr or "")[:300])
                return None
            return out_path.read_bytes()
    except Exception as ex:  # noqa: BLE001
        logger.warning("result_vision: render exception: %s", ex)
        return None


async def judge_result(
    *, png: bytes, user_goal: str, phase_goal: str, kind: str,
) -> dict[str, Any] | None:
    """vision judge：成品截圖 vs 目標。回 {passed: bool, reason, guidance}
    或 None（fail-open）。每 build 只呼叫一次（完工前），Haiku vision
    一張圖約 1-2K tokens。"""
    try:
        from python_ai_sidecar.agent_helpers_native.llm_client import AnthropicLLMClient
        from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
        settings = get_settings()
        api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("result_vision: no anthropic key — skip judge")
            return None
        client = AnthropicLLMClient(api_key=api_key, model=_JUDGE_MODEL)
        system = (
            "你是製程分析平台的成品審查員。你會拿到：使用者的建圖目標、最後一個"
            "階段的目標、以及最終成品（chart 或 table）的實際渲染截圖。"
            "就圖論圖，判斷成品是否達成目標的『可見要求』——例如：要求分色多序列"
            "就必須看得到多色 legend；要求管制線就要看得到 UCL/LCL 線；要求排序"
            "就看 x 軸順序；空圖/無資料一律不過。不要臆測圖上看不到的東西；"
            "數值精度不是審查範圍。只回 JSON："
            '{"passed": true|false, "reason": "一句話", '
            '"guidance": "不過時給 builder 的具體修法（提到該用的參數，如 series_field）"}'
        )
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(png).decode()}},
            {"type": "text", "text": f"建圖目標：{user_goal[:400]}\n"
                                     f"最終階段目標：{phase_goal[:300]}\n"
                                     f"成品型態：{kind}\n這是最終成品截圖，請審查。"},
        ]
        resp = await client.create(system=system,
                                   messages=[{"role": "user", "content": content}],
                                   max_tokens=400)
        text = (resp.text or "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            logger.warning("result_vision: judge no JSON: %s", text[:200])
            return None
        verdict = json.loads(text[start:end + 1])
        if not isinstance(verdict.get("passed"), bool):
            return None
        logger.info("result_vision: judge passed=%s reason=%s",
                    verdict.get("passed"), str(verdict.get("reason"))[:120])
        return verdict
    except Exception as ex:  # noqa: BLE001
        logger.warning("result_vision: judge exception: %s", ex)
        return None


# ── F1: chart_spec 成品層 deterministic 檢（零 LLM 成本，每輪都跑）──────────

_LIMIT_MARKERS = ("管制線", "管制限", "UCL", "LCL", "上下限", "control limit")
_SORT_MARKERS = ("時間排序", "按時間", "排序", "sorted by", "x 軸排序")


def chart_spec_gaps(spec: dict[str, Any], goal_text: str) -> list[str]:
    """檢查『執行後的成品 spec』與 phase 語意的落差；回缺口清單（空=過）。
    比參數閘（P2a）更後面一層：參數設了但沒生效（series 欄位全同值）也抓得到。"""
    gaps: list[str] = []
    data = spec.get("data") or []
    if not data:
        gaps.append("圖沒有資料（data 為空）— 檢查上游 filter 條件或期間")
        return gaps
    sf = spec.get("series_field")
    if sf:
        distinct = {str(r.get(sf)) for r in data if isinstance(r, dict)}
        if len(distinct) <= 1:
            gaps.append(
                f"series_field='{sf}' 只有 {len(distinct)} 個值（{', '.join(list(distinct)[:3])}）"
                "— 圖會是單色一條線。檢查上游是否被 filter 到只剩單一分組，"
                "或 series_field 該用別的欄位")
    if any(m in goal_text for m in _LIMIT_MARKERS):
        y = spec.get("y") or []
        y_list = y if isinstance(y, list) else [y]
        has_limits = bool(spec.get("rules")) or any(
            str(k).lower() in ("ucl", "lcl", "usl", "lsl") for k in y_list)
        if not has_limits:
            gaps.append("phase 要求管制線但成品沒有 rules 也沒有 ucl/lcl 序列 — "
                        "把上游的管制限欄位帶進 chart（rules 或 y 加 ucl/lcl）")
    return gaps
