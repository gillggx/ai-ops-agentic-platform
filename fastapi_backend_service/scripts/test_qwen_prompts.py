#!/usr/bin/env python3
"""test_qwen_prompts.py — Validate current prompts against Qwen2.5:32b via Ollama.

Usage:
    # Run all tests against Qwen (Ollama)
    cd fastapi_backend_service
    LLM_PROVIDER=ollama python scripts/test_qwen_prompts.py

    # Run against Claude for baseline comparison
    LLM_PROVIDER=anthropic python scripts/test_qwen_prompts.py

    # Run specific test group
    LLM_PROVIDER=ollama python scripts/test_qwen_prompts.py --group mcp_gen
    LLM_PROVIDER=ollama python scripts/test_qwen_prompts.py --group skill_diag
    LLM_PROVIDER=ollama python scripts/test_qwen_prompts.py --group intent_check

Output:
    Per-test PASS/FAIL with detailed failure reason.
    Summary table with pass rates per group.
    Saved to: scripts/qwen_test_results_<timestamp>.json
"""

import asyncio
import json
import os
import re
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Allow running from fastapi_backend_service root ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

# ─────────────────────────────────────────────────────────────────────────────
# Test data: realistic semiconductor fab scenarios
# ─────────────────────────────────────────────────────────────────────────────

SPC_DATA_SCHEMA = {
    "fields": [
        {"name": "lot_id", "type": "str", "description": "Lot ID"},
        {"name": "tool_id", "type": "str", "description": "Machine ID"},
        {"name": "operation_number", "type": "str", "description": "Operation code"},
        {"name": "measured_value", "type": "float", "description": "CD measured value (nm)"},
        {"name": "timestamp", "type": "str", "description": "Measurement time ISO8601"},
        {"name": "ucl", "type": "float", "description": "Upper Control Limit"},
        {"name": "lcl", "type": "float", "description": "Lower Control Limit"},
    ]
}

SPC_SAMPLE_ROW = {
    "lot_id": "L2603001",
    "tool_id": "TETCH01",
    "operation_number": "3200",
    "measured_value": 47.5,
    "timestamp": "2026-03-01T08:00:00",
    "ucl": 50.0,
    "lcl": 44.0,
}

SPC_SAMPLE_DATA = [SPC_SAMPLE_ROW.copy() for _ in range(5)]
SPC_SAMPLE_DATA[1]["measured_value"] = 51.2  # OOC point
SPC_SAMPLE_DATA[3]["measured_value"] = 43.1  # OOC point

APC_DATA_SCHEMA = {
    "fields": [
        {"name": "lot_id", "type": "str"},
        {"name": "tool_id", "type": "str"},
        {"name": "recipe_id", "type": "str"},
        {"name": "param_name", "type": "str", "description": "APC parameter name"},
        {"name": "value", "type": "float", "description": "Current parameter value"},
        {"name": "nominal", "type": "float", "description": "Nominal/target value"},
        {"name": "saturation_threshold", "type": "float", "description": "Max allowed deviation"},
        {"name": "timestamp", "type": "str"},
    ]
}

APC_SAMPLE_ROW = {
    "lot_id": "L2603001",
    "tool_id": "TETCH01",
    "recipe_id": "ETH_RCP_10",
    "param_name": "bias_power",
    "value": 98.5,
    "nominal": 100.0,
    "saturation_threshold": 5.0,
    "timestamp": "2026-03-01T08:00:00",
}

MCP_SAMPLE_OUTPUT = {
    "SPC_OOC_Check": {
        "dataset": [
            {"lot_id": "L2603001", "tool_id": "TETCH01", "measured_value": 51.2,
             "is_ooc": True, "deviation": 1.2, "timestamp": "2026-03-01T08:00:00"},
            {"lot_id": "L2603001", "tool_id": "TETCH01", "measured_value": 47.5,
             "is_ooc": False, "deviation": 0.0, "timestamp": "2026-03-01T09:00:00"},
        ],
        "output_schema": {"fields": [
            {"name": "lot_id", "type": "str"},
            {"name": "is_ooc", "type": "bool"},
            {"name": "deviation", "type": "float"},
        ]},
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json_safe(text: str) -> Optional[Dict]:
    """Try to extract JSON from LLM response, return None on failure."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx != -1:
            text = text[idx:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj
    except Exception:
        return None


def _extract_code_safe(text: str) -> Optional[str]:
    """Extract Python code block from LLM response."""
    m = re.search(r"```(?:python)?\s*([\s\S]+?)\s*```", text)
    if m:
        return m.group(1).strip()
    idx = text.find("def ")
    return text[idx:].strip() if idx != -1 else None


def check_mcp_gen_result(result: Dict) -> Tuple[bool, List[str]]:
    """Validate MCP generation output. Returns (passed, failures)."""
    failures = []

    # Must have processing_script
    script = result.get("processing_script", "")
    if not script:
        failures.append("❌ processing_script 缺失")
    elif "def process" not in script:
        failures.append("❌ processing_script 缺少 def process() 函式")
    else:
        # Check return keys
        if "output_schema" not in script and "\"output_schema\"" not in script:
            failures.append("⚠️ processing_script 可能缺少 output_schema 回傳")
        if "dataset" not in script:
            failures.append("⚠️ processing_script 可能缺少 dataset 回傳")
        if "ui_render" not in script:
            failures.append("⚠️ processing_script 可能缺少 ui_render 回傳")
        # Check forbidden patterns
        if "fig.to_html()" in script:
            failures.append("❌ 使用了禁止的 fig.to_html()")
        if "fig.to_json()" in script:
            failures.append("❌ 使用了禁止的 fig.to_json()")
        if "import pandas" in script:
            failures.append("❌ 不應在腳本中 import pandas（pd 已預注入）")
        if "import plotly" in script:
            failures.append("❌ 不應在腳本中 import plotly（go/px 已預注入）")

    # Must have output_schema with fields
    schema = result.get("output_schema", {})
    if not isinstance(schema.get("fields"), list):
        failures.append("❌ output_schema.fields 缺失或格式錯誤")

    # Must have summary
    if not result.get("summary"):
        failures.append("⚠️ summary 缺失")

    return len(failures) == 0, failures


def check_skill_diag_result(code: str) -> Tuple[bool, List[str]]:
    """Validate skill diagnosis code output."""
    failures = []
    if "def diagnose" not in code:
        failures.append("❌ 缺少 def diagnose() 函式")
    if '"status"' not in code and "'status'" not in code:
        failures.append("❌ 回傳 dict 缺少 status 欄位")
    if '"diagnosis_message"' not in code and "'diagnosis_message'" not in code:
        failures.append("❌ 回傳 dict 缺少 diagnosis_message 欄位")
    if '"problem_object"' not in code and "'problem_object'" not in code:
        failures.append("❌ 回傳 dict 缺少 problem_object 欄位")
    if "try:" not in code:
        failures.append("⚠️ 沒有 try/except 異常處理")
    return len(failures) == 0, failures


def check_intent_result(result: Dict) -> Tuple[bool, List[str]]:
    """Validate intent check JSON output."""
    failures = []
    if "is_clear" not in result:
        failures.append("❌ 缺少 is_clear 欄位")
    if not isinstance(result.get("questions"), list):
        failures.append("❌ questions 必須是陣列")
    if not result.get("improved_intent") and not result.get("suggested_prompt"):
        failures.append("❌ 缺少 improved_intent / suggested_prompt")
    return len(failures) == 0, failures


# ─────────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────────

MCP_GEN_CASES = [
    {
        "id": "mcp_gen_01",
        "desc": "SPC OOC 偵測 + 趨勢圖",
        "intent": "計算每筆 measured_value 是否超出 UCL/LCL，標記 OOC 點，並畫出帶 UCL/LCL 水平線的趨勢圖",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
        "sample": SPC_SAMPLE_ROW,
    },
    {
        "id": "mcp_gen_02",
        "desc": "APC 飽和度計算（無圖表，只需表格）",
        "intent": "計算每個參數與 nominal 的偏差百分比，若偏差超過 saturation_threshold 則標記為 SATURATED",
        "ds_name": "APC_Tuning_Data",
        "schema": APC_DATA_SCHEMA,
        "sample": APC_SAMPLE_ROW,
    },
    {
        "id": "mcp_gen_03",
        "desc": "SPC Cpk 計算",
        "intent": "計算所有 lot 的 Cpk（使用 USL=ucl, LSL=lcl），輸出每個 tool_id 的平均值、標準差和 Cpk 值",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
        "sample": SPC_SAMPLE_ROW,
    },
    {
        "id": "mcp_gen_04",
        "desc": "連續 OOC 連串規則（Nelson Rule 2）",
        "intent": "偵測連續 9 點在均值同側的連串異常（Nelson Rule 2），標記觸犯規則的批次群組",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
        "sample": SPC_SAMPLE_ROW,
    },
    {
        "id": "mcp_gen_05",
        "desc": "良率計算（表格輸出）",
        "intent": "計算各 tool_id 的 OOC 比例（ooc_count / total），按比例由高到低排序輸出表格",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
        "sample": SPC_SAMPLE_ROW,
    },
]

SKILL_DIAG_CASES = [
    {
        "id": "skill_diag_01",
        "desc": "SPC OOC 單點異常診斷",
        "diagnostic_prompt": "若 dataset 中有任何 is_ooc=True 的記錄，判定為 ABNORMAL，並列出異常 tool_id",
        "problem_subject": "SPC OOC 異常機台",
        "mcp_outputs": MCP_SAMPLE_OUTPUT,
    },
    {
        "id": "skill_diag_02",
        "desc": "空資料容錯",
        "diagnostic_prompt": "若 OOC 數量超過總記錄數的 20%，判定為 ABNORMAL",
        "problem_subject": "OOC 比例過高的機台",
        "mcp_outputs": {"SPC_Check": {"dataset": [], "output_schema": {"fields": []}}},
    },
    {
        "id": "skill_diag_03",
        "desc": "多 MCP 輸入診斷",
        "diagnostic_prompt": "若 deviation 欄位任意值超過 3.0，判定為 ABNORMAL，problem_object 記錄超標的 tool_id 和實際值",
        "problem_subject": "deviation 超標機台",
        "mcp_outputs": MCP_SAMPLE_OUTPUT,
    },
]

INTENT_CHECK_CASES = [
    {
        "id": "intent_01",
        "desc": "清晰意圖",
        "intent": "計算每筆 measured_value 是否超出 UCL/LCL，標記 OOC 點，使用 go.Scatter 畫趨勢圖",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
    },
    {
        "id": "intent_02",
        "desc": "模糊意圖（缺乏門檻值）",
        "intent": "找出異常的資料",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
    },
    {
        "id": "intent_03",
        "desc": "需要欄位對應的意圖",
        "intent": "計算移動平均線",
        "ds_name": "SPC_OOC_Etch_CD",
        "schema": SPC_DATA_SCHEMA,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

class PromptTestRunner:
    def __init__(self, provider: str):
        from app.utils.llm_client import get_llm_client, reset_llm_client
        reset_llm_client()
        os.environ["LLM_PROVIDER"] = provider
        # Force re-read config
        from app.config import get_settings
        import functools
        get_settings.cache_clear()
        self.llm = get_llm_client(force_provider=provider)
        self.provider = provider
        self.results: List[Dict] = []

    async def _call(self, system: str, user: str, max_tokens: int = 4096) -> Tuple[str, float]:
        t0 = time.time()
        resp = await self.llm.create(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        elapsed = time.time() - t0
        return resp.text, elapsed

    async def run_mcp_gen(self):
        from app.services.mcp_builder_service import _DEFAULT_TRY_RUN_SYSTEM_PROMPT
        print(f"\n{'='*60}")
        print(f"  GROUP: MCP Code Generation  [{self.provider.upper()}]")
        print(f"{'='*60}")

        for case in MCP_GEN_CASES:
            sample_section = f"\n真實資料範例（1 筆）：\n{json.dumps(case['sample'], ensure_ascii=False, indent=2)}\n⚠️ 欄位名稱必須完全按照範例，不可自行猜測或修改。\n"
            user_prompt = f"""以下是一個 DataSubject（資料源）的名稱與輸出格式：
DataSubject 名稱：{case['ds_name']}
輸出 Schema（Raw Format）：
{json.dumps(case['schema'], ensure_ascii=False, indent=2)}{sample_section}
使用者希望對此資料執行以下加工意圖：
「{case['intent']}」

請完成以下 4 項任務，以 JSON 格式回傳：

1. **processing_script**（str）：撰寫 Python 函式 `process(raw_data) -> dict`
2. **output_schema**（object）：{{"fields": [{{"name": str, "type": str, "description": str}}]}}
3. **ui_render_config**（object）：{{"chart_type": str, "x_axis": str, "y_axis": str, "series": [str], "notes": str}}
4. **input_definition**（object）：{{"params": [{{"name": str, "type": str, "source": str, "description": str, "required": bool}}]}}
5. **summary**（str）：一句話摘要

只回傳 JSON：
{{
  "processing_script": "...",
  "output_schema": {{}},
  "ui_render_config": {{}},
  "input_definition": {{}},
  "summary": "..."
}}"""

            print(f"\n  [{case['id']}] {case['desc']}")
            try:
                raw, elapsed = await self._call(_DEFAULT_TRY_RUN_SYSTEM_PROMPT, user_prompt, 8192)
                parsed = _extract_json_safe(raw)
                if parsed is None:
                    passed, failures = False, ["❌ JSON 解析失敗，原始輸出：" + raw[:200]]
                else:
                    passed, failures = check_mcp_gen_result(parsed)
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"  {status}  ({elapsed:.1f}s)")
                for f in failures:
                    print(f"    {f}")
                self.results.append({
                    "id": case["id"], "group": "mcp_gen", "desc": case["desc"],
                    "passed": passed, "failures": failures, "elapsed_s": round(elapsed, 1),
                    "provider": self.provider,
                })
            except Exception as e:
                print(f"  ❌ EXCEPTION: {e}")
                self.results.append({
                    "id": case["id"], "group": "mcp_gen", "desc": case["desc"],
                    "passed": False, "failures": [f"EXCEPTION: {e}"], "elapsed_s": 0,
                    "provider": self.provider,
                })

    async def run_skill_diag(self):
        from app.services.mcp_builder_service import _DEFAULT_SKILL_DIAG_SYSTEM_PROMPT
        print(f"\n{'='*60}")
        print(f"  GROUP: Skill Diagnosis Code Gen  [{self.provider.upper()}]")
        print(f"{'='*60}")

        for case in SKILL_DIAG_CASES:
            def _schema_preview(outputs):
                preview = {}
                for mcp_name, mcp_data in outputs.items():
                    if not isinstance(mcp_data, dict):
                        continue
                    dataset = mcp_data.get("dataset") or []
                    if dataset:
                        example = dataset[0]
                        columns = {k: type(v).__name__ for k, v in example.items()} if isinstance(example, dict) else {}
                        preview[mcp_name] = {"columns": columns, "example_row": example, "_total_rows": len(dataset)}
                    else:
                        preview[mcp_name] = {"columns": {}, "example_row": {}, "_total_rows": 0}
                return preview

            mcp_schema = _schema_preview(case["mcp_outputs"])
            user_prompt = f"""你是半導體製程智能診斷工程師。請根據以下信息，撰寫一個 Python 診斷函式。

【有問題的項目或物件】
{case['problem_subject']}

【異常判斷條件（Diagnostic Prompt）】
{case['diagnostic_prompt']}

【MCP 輸出欄位結構】
{json.dumps(mcp_schema, ensure_ascii=False, indent=2)}

只回傳 Python 程式碼區塊（不要有其他文字）。

⚠️ 必須以下列樣板開頭：
```python
def diagnose(mcp_outputs: dict) -> dict:
    rows = list(mcp_outputs.values())[0].get("dataset", [])
    if not rows:
        return {{"status": "NORMAL", "diagnosis_message": "無資料", "problem_object": {{}}}}
    ...
```

函式必須回傳包含 status / diagnosis_message / problem_object 三個 key 的 dict。"""

            print(f"\n  [{case['id']}] {case['desc']}")
            try:
                raw, elapsed = await self._call(_DEFAULT_SKILL_DIAG_SYSTEM_PROMPT, user_prompt, 4096)
                code = _extract_code_safe(raw) or raw
                passed, failures = check_skill_diag_result(code)
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"  {status}  ({elapsed:.1f}s)")
                for f in failures:
                    print(f"    {f}")
                self.results.append({
                    "id": case["id"], "group": "skill_diag", "desc": case["desc"],
                    "passed": passed, "failures": failures, "elapsed_s": round(elapsed, 1),
                    "provider": self.provider,
                })
            except Exception as e:
                print(f"  ❌ EXCEPTION: {e}")
                self.results.append({
                    "id": case["id"], "group": "skill_diag", "desc": case["desc"],
                    "passed": False, "failures": [f"EXCEPTION: {e}"], "elapsed_s": 0,
                    "provider": self.provider,
                })

    async def run_intent_check(self):
        print(f"\n{'='*60}")
        print(f"  GROUP: Intent Clarity Check  [{self.provider.upper()}]")
        print(f"{'='*60}")

        for case in INTENT_CHECK_CASES:
            user_prompt = f"""你是半導體製程系統整合專家。請完成以下兩項任務：

【任務一：評估加工意圖是否清晰】
資料源名稱：{case['ds_name']}
資料 Schema：
{json.dumps(case['schema'], ensure_ascii=False, indent=2)}

使用者加工意圖：「{case['intent']}」

【任務二：無論如何，都必須改寫一版更好的加工意圖】

請回傳 JSON（只回傳 JSON）：
{{
  "is_clear": true 或 false,
  "questions": ["若不清晰才填，最多3個問題；若已清晰則為空陣列"],
  "improved_intent": "改寫後的完整加工意圖",
  "changes": "一句話說明改寫了什麼"
}}"""

            print(f"\n  [{case['id']}] {case['desc']}")
            try:
                raw, elapsed = await self._call("", user_prompt, 700)
                parsed = _extract_json_safe(raw)
                if parsed is None:
                    passed, failures = False, ["❌ JSON 解析失敗，原始：" + raw[:200]]
                else:
                    passed, failures = check_intent_result(parsed)
                    if not passed or True:  # always show improved_intent
                        improved = parsed.get("improved_intent") or parsed.get("suggested_prompt") or ""
                        if improved:
                            print(f"    改寫意圖: {improved[:100]}")
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"  {status}  ({elapsed:.1f}s)")
                for f in failures:
                    print(f"    {f}")
                self.results.append({
                    "id": case["id"], "group": "intent_check", "desc": case["desc"],
                    "passed": passed, "failures": failures, "elapsed_s": round(elapsed, 1),
                    "provider": self.provider,
                })
            except Exception as e:
                print(f"  ❌ EXCEPTION: {e}")
                self.results.append({
                    "id": case["id"], "group": "intent_check", "desc": case["desc"],
                    "passed": False, "failures": [f"EXCEPTION: {e}"], "elapsed_s": 0,
                    "provider": self.provider,
                })

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  SUMMARY  [{self.provider.upper()}]")
        print(f"{'='*60}")
        groups = {}
        for r in self.results:
            g = r["group"]
            if g not in groups:
                groups[g] = {"pass": 0, "fail": 0, "total": 0}
            groups[g]["total"] += 1
            if r["passed"]:
                groups[g]["pass"] += 1
            else:
                groups[g]["fail"] += 1

        total_pass = sum(g["pass"] for g in groups.values())
        total = sum(g["total"] for g in groups.values())

        for g, stats in groups.items():
            rate = stats["pass"] / stats["total"] * 100 if stats["total"] else 0
            bar = "█" * int(rate / 10) + "░" * (10 - int(rate / 10))
            print(f"  {g:20s}  {bar}  {stats['pass']}/{stats['total']}  ({rate:.0f}%)")

        total_rate = total_pass / total * 100 if total else 0
        print(f"  {'TOTAL':20s}  {'─'*12}  {total_pass}/{total}  ({total_rate:.0f}%)")

        # Save results
        out_dir = Path(__file__).parent
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"qwen_test_results_{self.provider}_{ts}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({
                "provider": self.provider,
                "timestamp": ts,
                "pass_rate": f"{total_rate:.1f}%",
                "results": self.results,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n  Results saved: {out_file}")

        # Print failures for review
        failures = [r for r in self.results if not r["passed"]]
        if failures:
            print(f"\n  ── Failed Cases ({len(failures)}) ──")
            for r in failures:
                print(f"  [{r['id']}] {r['desc']}")
                for f in r["failures"]:
                    print(f"    {f}")


async def main():
    parser = argparse.ArgumentParser(description="Test LLM prompts against Qwen/Claude")
    parser.add_argument("--group", choices=["mcp_gen", "skill_diag", "intent_check", "all"], default="all")
    parser.add_argument("--provider", choices=["ollama", "anthropic"], default=None,
                        help="Override LLM_PROVIDER env var")
    args = parser.parse_args()

    provider = args.provider or os.environ.get("LLM_PROVIDER", "ollama")
    print(f"\n🧪 Prompt Test Runner — Provider: {provider.upper()}")
    print(f"   Model: {'qwen2.5:32b' if provider == 'ollama' else 'claude-sonnet-4-6'}")

    runner = PromptTestRunner(provider)

    if args.group in ("mcp_gen", "all"):
        await runner.run_mcp_gen()
    if args.group in ("skill_diag", "all"):
        await runner.run_skill_diag()
    if args.group in ("intent_check", "all"):
        await runner.run_intent_check()

    runner.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
