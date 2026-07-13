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
        # 校準（2026-07-13 首輪實測）：judge 曾挑「17.50 應為 17.5005」小數位、
        # 要求資料面沒有的機台、guidance 杜撰不存在的參數名 → 好圖被判死。
        # 原則：只攔「重大可見偏差」，拿不準一律放行；guidance 禁編參數。
        system = (
            "你是製程分析平台的成品審查員，判斷成品截圖是否達成目標的「重大"
            "可見要求」。只有下列情況才判不過：\n"
            "- 圖完全空白 / 沒有資料點\n"
            "- 要求多序列分色，但整張圖只有單一顏色一條線\n"
            "- 圖表型態與要求明顯不符（要散點圖卻畫成長條圖）\n"
            "- 要求管制線（UCL/LCL），但圖上完全沒有任何水平參考線\n"
            "- table：要求的關鍵欄位完全缺席\n"
            "以下一律「不算」缺陷（即使你覺得不完美）：數值小數位/四捨五入、"
            "圖例順序、序列數量與預期差一兩個（可能是資料面本來就沒有）、"
            "配色選擇、字體、label 被截斷、點的形狀、排版密度。"
            "拿不準 → passed=true（誤殺好圖比放過瑕疵嚴重）。\n"
            "guidance 規則：只描述「圖上少了什麼、該長什麼樣」——"
            "禁止杜撰或建議任何參數名（builder 會自己查 block 文件）。只回 JSON："
            '{"passed": true|false, "reason": "一句話", "guidance": "不過時的修法描述"}'
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
