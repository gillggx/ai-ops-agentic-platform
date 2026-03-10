"""MCP Builder Service — LLM-powered design-time assistant for MCP configuration.

Four LLM background tasks:
1. generate_script   : produce Python processing code from intent + DataSubject raw format
2. define_output_schema : derive new Dataset schema from the processing logic
3. suggest_ui_render  : recommend chart type / axes / config for the output
4. analyze_input      : identify what input params the processing needs
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import anthropic
from pydantic import BaseModel, ValidationError, field_validator

from app.config import get_settings
from app.utils.llm_utils import llm_retry

logger = logging.getLogger(__name__)
_MODEL = get_settings().LLM_MODEL

# ── Fallback prompts (used when DB has no entry yet) ─────────────────────────

_DEFAULT_GENERATE_PROMPT = """\
你是半導體製程系統整合專家，同時也是 Python 資料處理工程師。

以下是一個 DataSubject（資料源）的名稱與輸出格式：
DataSubject 名稱：{data_subject_name}
輸出 Schema（Raw Format）：
{data_subject_output_schema}

使用者希望對此資料執行以下加工意圖：
「{processing_intent}」

請完成以下 4 項任務，以 JSON 格式回傳：

1. **processing_script**（str）：
   - 撰寫一段 Python 函式 `process(raw_data: dict) -> dict`
   - raw_data 的結構符合上面的輸出 Schema
   - 根據加工意圖進行計算（例如：計算移動平均、標示 OOC、排序等）
   - 回傳 dict 必須符合標準輸出規範：{output_schema, dataset（統計摘要，不含原始 raw_data）, ui_render}
   - ui_render 格式：{"type": "trend_chart|bar_chart|table", "charts": [json.dumps(fig.to_dict()), ...], "chart_data": charts[0] 或 null}
   - 若有圖表需求，charts 陣列至少包含一個 json.dumps(fig.to_dict()) 字串；無圖表則 charts=[], chart_data=null
   - ⚠️⚠️ 絕對禁止使用 fig.to_html()、fig.write_html()、fig.to_json()；必須用 json.dumps(fig.to_dict()) ⚠️⚠️
   - 🔴 CRITICAL RULE (English): You MUST serialize charts using: import json; charts.append(json.dumps(fig.to_dict())). ANY use of fig.to_html() or fig.to_json() will cause the system to CRASH immediately. No exceptions.
   - ⚠️ Plotly v4+ API：禁止使用已棄用的 titlefont 屬性，改用 yaxis=dict(title=dict(text="...", font=dict(...)))
   - 沙盒可直接使用：pd、go、px、plt、np、json、math、deque、Counter、defaultdict（無需 import）

2. **output_schema**（object）：
   - 定義 process() 函式回傳值的 Schema
   - 格式：{{"fields": [{{"name": str, "type": str, "description": str}}]}}

3. **ui_render_config**（object）：
   - 根據輸出 Schema 建議最適合的圖表呈現方式
   - 格式：{{"chart_type": "trend|bar|table|scatter", "x_axis": str, "y_axis": str, "series": [str], "notes": str}}

4. **input_definition**（object）：
   - 分析此加工邏輯需要哪些 Input 參數
   - 格式：{{"params": [{{"name": str, "type": str, "source": "event|manual|data_subject", "description": str, "required": bool}}]}}

5. **summary**（str）：對整個 MCP 設計的一句話摘要

只回傳 JSON，不要有其他文字：
{{
  "processing_script": "...",
  "output_schema": {{}},
  "ui_render_config": {{}},
  "input_definition": {{}},
  "summary": "..."
}}"""

_DEFAULT_TRY_RUN_SYSTEM_PROMPT = """\
你是一位半導體製程資料處理工程師，你的唯一任務是依照使用者指示撰寫 Python 資料加工腳本。

【嚴格安全規範 — 違反即拒絕生成】
1. 腳本【絕對禁止】發起任何外部 HTTP 請求（禁止 requests, urllib, http.client 等）。
2. 腳本【絕對禁止】呼叫任何系統命令或 OS 操作（禁止 os, sys, subprocess, pathlib, shutil）。
3. 腳本【絕對禁止】讀寫任何實體檔案（禁止 open(), savefig('path') 等存檔至路徑操作）。
4. 腳本【絕對禁止】使用 eval(), exec(), compile(), __import__() 等反射操作。
5. 僅在以下情況才可拒絕：違反安全規範（規則 1-4），或意圖明確要求「發送通知 / 呼叫外部 API / 操作資料庫 / 控制硬體」等非計算行為。
   ✅ 以下全部屬於合法範疇，絕對不得拒絕（包含但不限於）：
   - 統計計算：mean、std、sigma、z-score、常態分佈、histogram、常態曲線疊加
   - 門檻判斷：是否超過 UCL/LCL、3-sigma rule、1/2 CL、Cp/Cpk、任何數值比較並輸出布林值
   - 異常標記：標記 OOC 點、輸出 status='NORMAL'/'ABNORMAL'、標注異常機台/批次
   - 視覺化：histogram + normal curve overlay、scatter、trend chart、直線標記 mean/σ 位置
   - SPC 相關：製程能力分析、管制界限計算、連串規則判斷、標記各 sigma 帶
   - 任何「計算後輸出分類、標記、統計摘要」的邏輯，一律視為合法統計運算

【沙盒可用 Python 環境 — 僅限以下清單，未列出的一律不可用】
⚠️【絕對禁止在腳本中 import pandas / import plotly / import matplotlib / import numpy】
以下變數已預先注入全域命名空間，直接呼叫即可，禁止重複 import：
  pd       → pandas（DataFrame 操作，直接用 pd.DataFrame(...)）
  go       → plotly.graph_objects（用 go.Figure(...)、go.Scatter(...) 等）
  px       → plotly.express（用 px.line(...)、px.bar(...) 等）
  plt      → matplotlib.pyplot（備用，直接用 plt.figure()、plt.plot() 等）
  matplotlib → matplotlib 模組
  np       → numpy（直接用 np.mean(...)、np.std(...)、np.array(...)、np.percentile(...) 等）

可 import 的標準函式庫（唯獨以下這些，其餘禁止）：
  math, statistics, json, datetime, collections, itertools, functools, io, base64

直接可用（已注入全域，無需 import）：
  deque（from collections）、OrderedDict、defaultdict、Counter、namedtuple

可用 Python 內建函式：
  abs, all, any, bool, bytes, bytearray, chr, classmethod, complex, dict, dir,
  divmod, enumerate, filter, float, format, frozenset, getattr, hasattr, hash,
  hex, id, int, isinstance, issubclass, iter, len, list, map, max, memoryview,
  min, next, object, oct, ord, pow, print, property, range, repr, reversed,
  round, set, setattr, slice, sorted, staticmethod, str, sum, super, tuple,
  type, vars, zip

可用 Exception 類別（可在 try/except 中使用）：
  Exception, BaseException, ValueError, TypeError, KeyError, IndexError,
  AttributeError, RuntimeError, StopIteration, NameError, NotImplementedError,
  ZeroDivisionError, OverflowError, ArithmeticError, ImportError,
  ModuleNotFoundError, LookupError, AssertionError, GeneratorExit

【重要注意事項】
- datetime 模組以物件形式注入，使用方式：datetime.datetime.now()、datetime.timedelta()、datetime.timezone.utc
- 可使用 from datetime import datetime, timedelta, timezone 語法
- ✅ np（numpy）已預注入，直接使用即可：np.mean(vals)、np.std(vals)、np.percentile(vals, 75)
  進階統計範例：skewness = float(((a - a.mean())**3).mean() / a.std()**3)，其中 a = np.array(vals)
- 不可使用 scipy、sklearn 等未列出的套件（np 已足夠做統計分析）
- try/except 必須使用上述已列出的 Exception 類別，例如 except Exception: 或 except ValueError:
- ⚠️ Exception Handling 鐵律：主診斷邏輯必須包在 try/except Exception as e 中：
  try:
      # 主要計算邏輯
  except Exception as e:
      return {"output_schema": {"fields": []}, "dataset": [], "ui_render": {"type": "table", "charts": [], "chart_data": None},
              "_error": f"執行異常：{e}"}
- ⚠️ 禁止使用 raise RuntimeError / raise ValueError 等主動拋出例外（改為回傳 _error 欄位）
- ⚠️ 禁止空 if 區塊（if condition: 後面必須有實際程式碼，不得僅有 pass 或空行）

【標準輸出規範 — process() 函式的回傳 dict 必須包含以下三個 Key】
- output_schema: {"fields": [{"name": str, "type": str, "description": str}]}
- dataset: 統計摘要資料陣列（list of dict），為 process() 計算後的彙整結果，不要回傳原始 raw_data
- ui_render: {
    "type": "trend_chart" | "bar_chart" | "scatter_chart" | "table",
    "charts": ["Plotly JSON 字串 1", "Plotly JSON 字串 2"],  # 一個或多個圖表；若無圖表則為空陣列 []
    "chart_data": "Plotly JSON 字串 1"  # 與 charts[0] 相同（向下相容用）；若無圖表則為 null
  }

⚠️⚠️ 絕對禁止使用 fig.to_html()、fig.write_html()、fig.show()、任何 HTML 輸出方式 ⚠️⚠️
必須使用 json.dumps(fig.to_dict()) — 禁止用 fig.to_json()（可能產生二進位輸出）

⚠️ Plotly Layout 現代 API（v4+）— 禁止使用已棄用屬性：
- ❌ 禁止：yaxis=dict(titlefont=dict(...))  → ✅ 改用：yaxis=dict(title=dict(text="...", font=dict(...)))
- ❌ 禁止：layout.titlefont  → ✅ 改用：layout.title.font
- ❌ 禁止：xaxis/yaxis 的 titlefont 屬性 → ✅ 改用 title=dict(font=dict(size=12, color="black"))

【繪圖規範 — 需要圖表時（trend_chart / bar_chart / scatter_chart）必須有至少一張】
⚠️ 關鍵規則：每一條要顯示的資料線都必須獨立加入 go.Figure()。以 SPC Trend Chart 為例，
你必須分別呼叫 fig.add_trace() 四次：(1) 主值折線、(2) UCL 水平線、(3) LCL 水平線、(4) OOC 散點標記。
千萬不能漏掉任何一條 trace。

⚠️ 若使用者要求 N 張圖，charts 陣列必須包含 N 個 json.dumps(fig.to_dict()) 字串，每張圖建立一個獨立的 go.Figure()。

- Plotly 單圖骨架（SPC Trend Chart，4 traces 標準格式）：
  charts = []
  fig = go.Figure()
  # ① 主值折線（最重要，絕對不可省略，顏色用 green）
  fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode='lines+markers',
      name='Value', line=dict(color='green'), marker=dict(color='green')))
  # ② UCL 水平線（顏色 orange, dash）
  fig.add_trace(go.Scatter(x=x_vals, y=[ucl]*len(x_vals), mode='lines',
      name='UCL', line=dict(color='orange', dash='dash')))
  # ③ LCL 水平線（顏色 orange, dash）
  fig.add_trace(go.Scatter(x=x_vals, y=[lcl]*len(x_vals), mode='lines',
      name='LCL', line=dict(color='orange', dash='dash')))
  # ④ OOC 異常點（顏色 red，超出 UCL 或低於 LCL 的點）
  ooc_mask = [(v > ucl or v < lcl) for v in y_vals]
  ooc_x = [x for x, m in zip(x_vals, ooc_mask) if m]
  ooc_y = [y for y, m in zip(y_vals, ooc_mask) if m]
  if ooc_x:
      fig.add_trace(go.Scatter(x=ooc_x, y=ooc_y, mode='markers',
          name='OOC', marker=dict(color='red', size=10)))
  fig.update_layout(
      title=dict(text='Chart 1 Title', y=0.97, x=0, xanchor='left'),
      xaxis_title='X', yaxis_title='Y',
      height=360,
      margin=dict(l=50, r=20, t=55, b=100),
      legend=dict(orientation='h', y=-0.28, x=0, xanchor='left')
  )
  charts.append(json.dumps(fig.to_dict()))   # ← append 後再建第 2 張

- Plotly 多圖骨架（若使用者要求 2 張圖，照此模式建立第 2 個 fig）：
  # ── 第 2 張圖 ──────────────────────────────────────────────────
  fig2 = go.Figure()
  # 按需加入 traces（參考上方骨架）
  fig2.add_trace(go.Scatter(...))
  fig2.update_layout(title='Chart 2 Title', ...)
  charts.append(json.dumps(fig2.to_dict()))  # ← 同樣 append 進 charts
  # 最終 ui_render 含所有圖表
  ui_render = {"type": "trend_chart", "charts": charts, "chart_data": charts[0]}

- Matplotlib（備選，僅需單張時）：
  buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0)
  chart_data = 'data:image/png;base64,' + base64.b64encode(buf.read()).decode()
  ui_render = {"type": "trend_chart", "charts": [chart_data], "chart_data": chart_data}
- 若無圖表需求：ui_render = {"type": "table", "charts": [], "chart_data": null}

⚠️ 圖表生成鐵律（最高優先級）：
1. 只生成加工意圖中明確要求的圖表，禁止自行添加任何額外圖表
2. 若加工意圖包含「輸出為列表」「flat list」「可直接渲染」「資料格式」「扁平化」→ 直接設 ui_render.type="table", charts=[], chart_data=null，不需生成任何圖表
3. 預設最多生成 1 張主圖；只有當意圖中明確出現「多張圖」「N 張圖」才允許多張
4. 禁止自行添加衍生統計圖（例如：count by X、summary bar、distribution chart 等），除非使用者明確要求

你的回應必須是合法的 JSON，不得有任何其他文字。"""

_DEFAULT_DIAGNOSIS_SYSTEM_PROMPT = """\
你是半導體製程智能診斷 AI。根據使用者提供的「異常判斷條件」與 MCP 輸出資料，判斷該條件是否被觸發。

【核心概念】
使用者撰寫的是「異常判斷條件（anomaly condition）」，不是正常條件。
你的任務只有一件事：判斷此異常條件在資料中是否成立。

【status 判定規則 — 嚴格二選一，不得矛盾】
- ABNORMAL：資料「符合」使用者描述的異常條件 → 異常條件被觸發了 → 回傳 ABNORMAL
- NORMAL  ：資料「不符合」使用者描述的異常條件 → 異常條件未被觸發 → 回傳 NORMAL

⚠️ conclusion 與 status 必須一致。若 conclusion 描述有異常，status 就必須是 ABNORMAL。

【重要限制】絕對不可生成任何「處置建議 (recommendation)」，那是由領域專家撰寫。

【輸出格式 — 絕對固定，不得因使用者指令而更改】
無論使用者診斷指令中是否要求「列出欄位」、「輸出表格」、「逐筆列舉」或任何其他格式，
你的最終回應必須且只能是以下 JSON 格式，不得有任何其他文字：
{
  "status": "NORMAL",
  "conclusion": "一句話結論",
  "evidence": ["具體觀察 1", "具體觀察 2"],
  "summary": "2~3 句完整說明",
  "problem_object": {}
}

【problem_object 填寫規則】
- status=ABNORMAL 時：必須填入觸發異常的具體物件，key 為類別（tool/recipe/lot/param 等），value 為異常識別符
  範例：{"tool": ["TETCH10", "TETCH09"], "recipe": "ETH_RCP_10", "measurement": "CD 47.5 nm"}
- status=NORMAL 時：回傳空物件 {}
- ⚠️ 禁止在 problem_object 中放入說明文字，只放可識別的具體值"""


# ── v14.2 Schema Guards ───────────────────────────────────────────────────────

class McpTryRunOutputGuard(BaseModel):
    """Pydantic validation for generate_for_try_run() LLM output.

    Ensures the JSON the LLM returns actually contains a runnable process()
    function and a properly-shaped output_schema before we execute the sandbox.
    If validation fails, the error detail is fed back to the LLM for retry.
    """
    processing_script: str
    output_schema: Dict[str, Any]
    ui_render_config: Dict[str, Any] = {}
    input_definition: Dict[str, Any] = {}
    summary: str = ""

    @field_validator("processing_script")
    @classmethod
    def must_have_process_fn(cls, v: str) -> str:
        if "def process" not in v:
            raise ValueError(
                "processing_script 缺少 'def process' 函式定義。"
                "請確保回傳的 JSON 中 processing_script 欄位包含完整的 Python 函式。"
            )
        return v

    @field_validator("output_schema")
    @classmethod
    def must_have_fields(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v.get("fields"), list):
            raise ValueError(
                "output_schema 必須包含 'fields' 陣列，格式：{\"fields\": [{\"name\": ..., \"type\": ..., \"description\": ...}]}"
            )
        return v


class SkillCodeOutputGuard:
    """Validator for generate_code_diagnosis() Python code output.

    Not a Pydantic model because the output is raw Python, not JSON.
    Validates structural requirements and returns the error string for LLM retry.
    """

    @staticmethod
    def validate(code: str) -> str:
        """Raise ValueError with detail if code is invalid, else return code."""
        errors = []
        if "def diagnose" not in code:
            errors.append("缺少 'def diagnose' 函式定義（必須以 def diagnose(mcp_outputs: dict) -> dict: 開頭）")
        if '"status"' not in code and "'status'" not in code:
            errors.append("回傳 dict 缺少 'status' 鍵（必須回傳 NORMAL 或 ABNORMAL）")
        if '"diagnosis_message"' not in code and "'diagnosis_message'" not in code:
            errors.append("回傳 dict 缺少 'diagnosis_message' 鍵")
        if '"problem_object"' not in code and "'problem_object'" not in code:
            errors.append("回傳 dict 缺少 'problem_object' 鍵")
        if errors:
            raise ValueError(
                "生成的 diagnose() 函式結構不完整：\n"
                + "\n".join(f"  - {e}" for e in errors)
                + "\n\n請修正並確保所有 3 個必要 key 都存在於回傳的 dict 中。"
            )
        return code


# ─────────────────────────────────────────────────────────────────────────────


def _get_text(content: list) -> str:
    """Return the text from the first TextBlock (skips ThinkingBlocks)."""
    for block in content:
        if hasattr(block, "text"):
            return block.text
    return ""


def _extract_json(raw: str) -> Dict[str, Any]:
    """Strip markdown fences and parse the first valid JSON object found.

    Uses json.JSONDecoder.raw_decode() so trailing text / multiple objects
    after the first closing brace never cause 'Extra data' errors.
    """
    text = raw.strip()
    # Strategy 1: explicit ``` fences (with or without 'json' tag)
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    # Strategy 2: skip leading non-JSON text to find the first '{'
    if not text.startswith("{"):
        idx = text.find("{")
        if idx != -1:
            text = text[idx:]
    # Strategy 3: raw_decode — parses only the first valid JSON object,
    # ignoring any trailing text or extra JSON objects.
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj
    except json.JSONDecodeError as exc:
        # LLM returned plain text instead of JSON — treat as general_chat reply
        logger.error(
            "_extract_json FAILED: %s | first_300_chars=%r | last_300_chars=%r",
            exc, raw[:300], raw[-300:]
        )
        return {"intent": "general_chat", "reply_message": raw.strip(), "is_ready": False}


class MCPBuilderService:
    """LLM-powered design-time helper for the MCP Builder."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate_all(
        self,
        processing_intent: str,
        data_subject_name: str,
        data_subject_output_schema: Dict[str, Any],
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run all 4 LLM tasks in a single prompt and return combined result.

        Args:
            processing_intent: Natural language goal, e.g. "計算移動平均線並標示 OOC 點位"
            data_subject_name: Name of the source DataSubject
            data_subject_output_schema: The raw output schema from the DataSubject
            prompt_template: Optional override from DB (SystemParameter PROMPT_MCP_GENERATE).
                             Must contain {data_subject_name}, {data_subject_output_schema},
                             {processing_intent} placeholders.

        Returns:
            dict with keys: processing_script, output_schema, ui_render_config, input_definition, summary
        """
        template = prompt_template or _DEFAULT_GENERATE_PROMPT
        prompt = template.format(
            data_subject_name=data_subject_name,
            data_subject_output_schema=json.dumps(
                data_subject_output_schema, ensure_ascii=False, indent=2
            ),
            processing_intent=processing_intent,
        )

        last_err: Exception = RuntimeError("generate_all: no attempts made")
        for attempt in range(2):
            try:
                response = await self._client.messages.create(
                    model=_MODEL,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )
                return _extract_json(_get_text(response.content))
            except (json.JSONDecodeError, ValueError) as exc:
                last_err = exc
                logger.warning("generate_all JSON parse failed (attempt %d): %s", attempt + 1, exc)
        raise ValueError(f"LLM 生成失敗：{last_err}")

    async def generate_for_try_run(
        self,
        processing_intent: str,
        data_subject_name: str,
        data_subject_output_schema: Dict[str, Any],
        system_prompt: Optional[str] = None,
        sample_row: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Same as generate_all() but with strict guardrails in the system prompt.

        Used exclusively for the Try Run flow so the generated script is safe to
        execute in the sandbox.

        Args:
            system_prompt: Optional override from DB (SystemParameter PROMPT_MCP_TRY_RUN).
            sample_row: One row of real data so LLM can see exact column names/format.
        """
        sys_prompt = system_prompt or _DEFAULT_TRY_RUN_SYSTEM_PROMPT

        sample_section = ""
        if sample_row is not None:
            sample_section = f"""\n真實資料範例（1 筆）：
{json.dumps(sample_row, ensure_ascii=False, indent=2)}
⚠️ 欄位名稱必須完全按照範例，不可自行猜測或修改。
"""

        prompt = f"""以下是一個 DataSubject（資料源）的名稱與輸出格式：
DataSubject 名稱：{data_subject_name}
輸出 Schema（Raw Format）：
{json.dumps(data_subject_output_schema, ensure_ascii=False, indent=2)}{sample_section}
使用者希望對此資料執行以下加工意圖：
「{processing_intent}」

請完成以下 4 項任務，以 JSON 格式回傳：

1. **processing_script**（str）：
   - 撰寫 Python 函式 `process(raw_data) -> dict`
   - raw_data 可能是 list（如 SPC、APC_tuning 等陣列型資料源）或 dict（單筆記錄型資料源），請根據輸出 Schema 判斷並正確處理
   - 若 raw_data 是 list，直接以 `for row in raw_data` 迭代即可；若是 dict，直接存取欄位
   - 根據加工意圖進行純資料計算（遵守上方安全規範，不得存檔）
   - 回傳的 dict 必須包含 output_schema, dataset, ui_render 三個 Key（遵守標準輸出規範）

2. **output_schema**（object）：
   - 定義 process() 回傳值中 dataset 的欄位 Schema
   - 格式：{{"fields": [{{"name": str, "type": str, "description": str}}]}}

3. **ui_render_config**（object）：
   - 建議最適合的圖表呈現方式
   - 格式：{{"chart_type": "trend|bar|table|scatter", "x_axis": str, "y_axis": str, "series": [str], "notes": str}}
   - 若資料適合用表格呈現（無明顯時序或數值序列），chart_type 請設為 "table"

4. **input_definition**（object）：
   - 分析此加工邏輯需要哪些 Input 參數
   - 格式：{{"params": [{{"name": str, "type": str, "source": "event|manual|data_subject", "description": str, "required": bool}}]}}

5. **summary**（str）：對整個 MCP 設計的一句話摘要

只回傳 JSON：
{{
  "processing_script": "...",
  "output_schema": {{}},
  "ui_render_config": {{}},
  "input_definition": {{}},
  "summary": "..."
}}"""

        # v14.2: use llm_retry so that McpTryRunOutputGuard validation errors
        # are fed back to the LLM as error_context on the next attempt.
        _attempt_count = [0]
        _events: List[str] = []
        _guard_failures = [0]

        async def _call(error_context: Optional[str]) -> Dict[str, Any]:
            retry_suffix = ""
            if error_context:
                retry_suffix = (
                    f"\n\n⚠️ 上一次生成的輸出驗證失敗，請修正以下問題後重新生成：\n{error_context}"
                )
                _events.append(f"[Schema Guard] 注入驗證錯誤，發起第 {_attempt_count[0] + 1} 次重試…")
            full_prompt = prompt + retry_suffix
            _attempt_count[0] += 1
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=8192,
                system=sys_prompt,
                messages=[{"role": "user", "content": full_prompt}],
            )
            raw_text = _get_text(response.content)
            logger.info(
                "generate_for_try_run raw LLM response (attempt %d): stop_reason=%s len=%d first_200=%r",
                _attempt_count[0], response.stop_reason, len(raw_text), raw_text[:200],
            )
            return _extract_json(raw_text)

        def _validate(result: Dict[str, Any]) -> Dict[str, Any]:
            try:
                McpTryRunOutputGuard.model_validate(result)
            except ValidationError as exc:
                _guard_failures[0] += 1
                err_short = str(exc).splitlines()[0][:80]
                _events.append(f"[Schema Guard ✗] 第 {_attempt_count[0]} 次驗證失敗：{err_short}")
                # Convert Pydantic error to a plain string the LLM can read
                raise ValueError(str(exc)) from exc
            return result

        result = await llm_retry(_call, _validate, max_retries=2)
        if _guard_failures[0] == 0:
            _events.append("[Schema Guard ✓] MCP 結構驗證通過（def process ✓ · output_schema.fields ✓）")
        else:
            _events.append(
                f"[Schema Guard ✓] 結構驗證通過（共嘗試 {_attempt_count[0]} 次，修正 {_guard_failures[0]} 次失敗）"
            )
        result["_learning_events"] = _events
        return result

    async def analyze_error(
        self,
        script: str,
        error_message: str,
        processing_intent: str,
        data_subject_name: str,
    ) -> str:
        """Ask the LLM to explain why a sandbox execution failed and suggest fixes.

        Returns a plain-text analysis in Traditional Chinese.
        """
        prompt = f"""以下是一段 LLM 生成的 Python MCP 腳本，在沙盒執行時發生錯誤。

【加工意圖】
{processing_intent}

【資料源】
{data_subject_name}

【生成的腳本】
```python
{script}
```

【錯誤訊息】
{error_message}

【沙盒限制說明】
- 僅允許 math, statistics, json, datetime, collections, itertools, functools, io, base64, pandas (pd), plotly.graph_objects (go) 等白名單套件
- 禁止 os, sys, subprocess, requests, open(), eval(), exec() 等危險操作
- 禁止任何磁碟寫入；繪圖需用記憶體（io.BytesIO）

請用繁體中文回答以下三點：
1. **錯誤原因**：這個錯誤是什麼意思，為什麼發生？
2. **腳本問題**：腳本哪裡寫錯了（具體行數或邏輯）？
3. **修改建議**：使用者應如何調整加工意圖或腳本邏輯來修正？"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return _get_text(response.content)

    async def check_intent(
        self,
        processing_intent: str,
        data_subject_name: str,
        data_subject_output_schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check if the processing intent is clear and unambiguous before generation.

        Returns:
            dict with keys: is_clear (bool), questions (list[str])
        """
        prompt = f"""你是半導體製程系統整合專家。請完成以下兩項任務：

【任務一：評估加工意圖是否清晰】
資料源名稱：{data_subject_name}
資料 Schema：
{json.dumps(data_subject_output_schema, ensure_ascii=False, indent=2)}

使用者加工意圖：「{processing_intent}」

常見不清晰問題：
- 計算參數未指定（例如移動平均未說明窗口大小）
- 控制限未指定（例如 OOC 判定標準不明）
- 輸出格式不明確
- 意圖本身模糊或矛盾

【任務二：無論如何，都必須改寫一版更好的加工意圖】
改寫原則：
- 引用 Schema 中的具體欄位名稱
- 加入具體計算參數（窗口大小、門檻值等）
- 明確說明輸出結果格式
- 語意清晰、可直接生成 Python 腳本

請回傳 JSON（只回傳 JSON，不要有其他文字）：
{{
  "is_clear": true 或 false,
  "questions": ["若不清晰才填，最多3個問題；若已清晰則為空陣列"],
  "improved_intent": "改寫後的完整加工意圖（一定要填，即使原本已清晰也提供更精確的版本）",
  "changes": "一句話說明改寫了什麼（例如：補充窗口大小7筆與±3σ控制限）"
}}"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            data = _extract_json(_get_text(response.content))
            # Backward-compat: keep suggested_prompt alias
            data.setdefault("improved_intent", data.get("suggested_prompt", ""))
            data.setdefault("suggested_prompt", data.get("improved_intent", ""))
            data.setdefault("changes", "")
            data.setdefault("questions", [])
            data.setdefault("is_clear", True)
            return data
        except Exception:
            return {"is_clear": True, "questions": [], "improved_intent": "", "suggested_prompt": "", "changes": ""}

    async def check_diagnosis_intent(
        self,
        diagnostic_prompt: str,
        mcp_output_sample: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyse the diagnostic prompt and always produce an improved version.

        Returns:
            dict with keys:
              is_clear (bool)       — whether the original prompt was already clear
              questions (list[str]) — clarifying questions if not clear (max 3)
              improved_prompt (str) — polished/improved prompt (always provided)
              changes (str)         — brief note on what was improved
        """
        prompt = f"""你是半導體製程智能診斷系統設計師。
請完成以下兩項任務：

【任務一：評估診斷 Prompt 是否清晰】
常見問題：
- 判斷欄位未對應到 MCP 輸出的具體欄位名稱
- 數值門檻未明確指定（如「超過正常值」但未說明多少算正常）
- 沒有明確說明要判斷哪個方向（過高？過低？逾期？缺少？）
- 結論格式不明（沒有說何時算 NORMAL，何時算 ABNORMAL）

【任務二：無論如何，都必須改寫一版更好的診斷 Prompt】
改寫原則：
- 明確引用 MCP 輸出中的具體欄位名稱
- 加入具體的數值門檻或時間條件
- 明確說明哪些情況判為 NORMAL，哪些情況判為 ABNORMAL
- 語意清晰、可直接執行
- ⚠️ 絕對不可在改寫版本中加入「輸出時請列出...」、「列出每筆...」、「以表格呈現...」等輸出格式指令
  （診斷系統有固定的 JSON 輸出格式，使用者指令只需描述判斷條件，不需指定輸出格式）

【MCP 輸出資料樣本（供參考欄位名稱）】
{json.dumps(mcp_output_sample, ensure_ascii=False, indent=2)}

【使用者的原始診斷 Prompt】
「{diagnostic_prompt}」

請回傳 JSON（只回傳 JSON，不要有其他文字）：
{{
  "is_clear": true 或 false,
  "questions": ["若不清晰才填，最多3個問題；若已清晰則為空陣列"],
  "improved_prompt": "改寫後的完整診斷 Prompt（一定要填，即使原本已清晰也提供更精確的版本）",
  "changes": "一句話說明改寫了什麼（例如：補充具體欄位名稱與3天時間門檻）"
}}"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            data = _extract_json(_get_text(response.content))
            # Normalise: keep backward-compat `suggested_prompt` alias
            data.setdefault("improved_prompt", data.get("suggested_prompt", ""))
            data.setdefault("suggested_prompt", data.get("improved_prompt", ""))
            data.setdefault("changes", "")
            data.setdefault("questions", [])
            data.setdefault("is_clear", True)
            return data
        except Exception:
            return {"is_clear": True, "questions": [], "improved_prompt": "", "suggested_prompt": "", "changes": ""}

    async def triage_error(
        self,
        script: str,
        error_message: str,
        processing_intent: str,
        data_subject_name: str,
    ) -> Dict[str, Any]:
        """Classify sandbox error into User_Prompt_Issue or System_Issue.

        Returns dict with keys:
          error_type: "User_Prompt_Issue" | "System_Issue"
          error_reason: plain-text root cause (zh-TW)
          script_issue: specific script problem (zh-TW)
          suggested_prompt: improved intent if User_Prompt_Issue, else ""
          fix_suggestion: actionable advice (zh-TW)
        """
        prompt = f"""以下是一段 LLM 生成的 Python MCP 腳本，在沙盒執行時發生錯誤。

【加工意圖】
{processing_intent}

【資料源】
{data_subject_name}

【生成的腳本】
```python
{script}
```

【錯誤訊息】
{error_message}

【沙盒限制說明】
- 僅允許 math, statistics, json, datetime, collections, itertools, functools, io, base64
- 預注入全域變數：pd（pandas）、go（plotly.graph_objects）、px（plotly.express）、plt（matplotlib.pyplot）
- 禁止 os, sys, subprocess, requests, open(), eval(), exec() 等危險操作
- 禁止任何磁碟寫入；繪圖需用記憶體（io.BytesIO）

【錯誤分類標準】
- User_Prompt_Issue：錯誤根本原因是使用者的加工意圖不夠明確或有邏輯問題，導致 LLM 生成了無法執行的腳本。例如：意圖中缺少關鍵參數（窗口大小、控制限值）、邏輯自相矛盾、欄位名稱不存在等。
- System_Issue：錯誤根本原因是沙盒環境限制、套件版本衝突、記憶體不足、或其他系統層面問題，與使用者意圖無關。

請只回傳 JSON（繁體中文說明）：
{{
  "error_type": "User_Prompt_Issue 或 System_Issue",
  "error_reason": "這個錯誤發生的根本原因（1-2句）",
  "script_issue": "腳本中具體哪裡有問題（1-2句）",
  "suggested_prompt": "若 error_type=User_Prompt_Issue，回傳修正後的加工意圖（要比原本更具體清楚）；若 error_type=System_Issue，回傳空字串",
  "fix_suggestion": "建議使用者採取的行動（1-2句）"
}}"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            return _extract_json(_get_text(response.content))
        except Exception as exc:
            logger.warning("triage_error JSON parse failed: %s", exc)
            return {
                "error_type": "System_Issue",
                "error_reason": str(error_message),
                "script_issue": "",
                "suggested_prompt": "",
                "fix_suggestion": "請聯繫 IT 支援",
            }

    async def try_diagnosis(
        self,
        diagnostic_prompt: str,
        mcp_outputs: Dict[str, Any],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Simulate Skill diagnosis: send MCP sample outputs + user prompt to LLM.

        Returns a structured diagnosis report with conclusion, severity, evidence, summary.
        NOTE: recommendation is intentionally excluded — experts write that separately.

        Args:
            system_prompt: Optional override from DB (SystemParameter PROMPT_SKILL_DIAGNOSIS).
        """
        sys_prompt = system_prompt or _DEFAULT_DIAGNOSIS_SYSTEM_PROMPT

        prompt = f"""MCP 輸出資料（試跑樣本）：
{json.dumps(mcp_outputs, ensure_ascii=False, indent=2)}

使用者診斷邏輯指令：
{diagnostic_prompt}

請根據上述資料與診斷邏輯，輸出結構化診斷報告："""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=sys_prompt,
            messages=[{"role": "user", "content": prompt}],
        )

        text = _get_text(response.content).strip()
        try:
            data = _extract_json(text)
            # Accept both 'status' (NORMAL/ABNORMAL) and legacy 'severity' (LOW/MEDIUM/HIGH/CRITICAL)
            raw_status = data.get("status") or ""
            if not raw_status:
                sev = (data.get("severity") or "").upper()
                raw_status = "NORMAL" if sev == "LOW" else "ABNORMAL"
            # Normalize to binary NORMAL / ABNORMAL
            status = "NORMAL" if raw_status.upper() == "NORMAL" else "ABNORMAL"
            prob_obj = data.get("problem_object", {})
            # Discard the instructional placeholder if LLM echoed it back verbatim
            if isinstance(prob_obj, dict) and "說明" in prob_obj and len(prob_obj) == 1:
                prob_obj = {}
            return {
                "status": status,
                "conclusion": data.get("conclusion", ""),
                "evidence": data.get("evidence", []),
                "summary": data.get("summary", ""),
                "problem_object": prob_obj,
            }
        except Exception:
            logger.warning("try_diagnosis JSON parse failed; raw=%s", text[:200])
            # Fallback: treat whole text as summary, flag as ambiguous warning
            return {"status": "ABNORMAL", "conclusion": "LLM 回應解析失敗", "evidence": [], "summary": text, "problem_object": {}}

    async def summarize_diagnosis(
        self,
        python_result: Dict[str, Any],
        diagnostic_prompt: str,
        mcp_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate a human-readable summary from Python sandbox diagnosis result.

        Called at runtime after ``execute_diagnose_fn()`` succeeds.

        Args:
            python_result: Output of diagnose() — {status, diagnosis_message, problem_object}.
            diagnostic_prompt: The skill's stored diagnostic_prompt (context for LLM).
            mcp_outputs: The MCP final dataset used as diagnose() input.

        Returns:
            Dict with key ``summary`` (2-3 sentence Chinese explanation).
        """
        status = python_result.get("status", "UNKNOWN")
        diag_msg = python_result.get("diagnosis_message", "")
        prob_obj = python_result.get("problem_object", {})

        prompt = f"""你是半導體製程診斷AI。以下是 Python 診斷函式的執行結果：

診斷狀態：{status}
診斷訊息：{diag_msg}
異常物件：{json.dumps(prob_obj, ensure_ascii=False)}

診斷邏輯說明（背景）：{diagnostic_prompt}

請用 2-3 句繁體中文，對此次診斷結果做清晰的摘要說明。
- 若 NORMAL：說明為何判定正常
- 若 ABNORMAL：說明偵測到什麼異常、影響範圍

只回傳 JSON：{{"summary": "..."}}"""

        try:
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(_get_text(response.content))
            return {"summary": data.get("summary", diag_msg)}
        except Exception as exc:
            logger.warning("summarize_diagnosis failed: %s", exc)
            return {"summary": diag_msg}

    async def explain_failure(
        self,
        stage: str,
        error: str,
        context: Dict[str, Any],
    ) -> str:
        """Generate a concise human-readable failure explanation using LLM.

        Called when any stage of the Skill pipeline fails (DS fetch, MCP script,
        empty dataset, or Skill Python exception).  Always returns a string —
        falls back to ``"{stage} 失敗：{error}"`` if the LLM call itself fails.

        Args:
            stage: Display name of the failed stage (e.g. "MCP 腳本執行").
            error: Raw exception message or error description.
            context: Additional key/value context (MCP name, params used, etc.).
        """
        prompt = f"""你是半導體製程智能診斷系統。
以下是診斷流程在「{stage}」階段發生的失敗：

錯誤訊息：{error}
相關上下文：{json.dumps(context, ensure_ascii=False)}

請用 1-2 句繁體中文清楚說明：
1. 哪個步驟失敗了
2. 可能的原因或建議處置方式

只回傳 JSON：{{"explanation": "..."}}"""
        try:
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(_get_text(response.content))
            return data.get("explanation", error)
        except Exception as exc:
            logger.warning("explain_failure LLM call failed: %s", exc)
            return f"{stage} 失敗：{error}"

    async def check_code_diagnosis_intent(
        self,
        diagnostic_prompt: str,
        problem_subject: Optional[str],
        mcp_output_sample: Dict[str, Any],
        event_attributes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Check clarity of diagnostic_prompt + problem_subject for code generation.

        Returns dict with: is_clear, questions, suggested_prompt,
                           suggested_problem_subject, changes
        """
        prompt = f"""你是半導體製程智能診斷系統設計師。
請評估以下診斷配置是否適合生成 Python 診斷函式，並提供改善建議。

【觸發此 Skill 的事件屬性（Skill 輸入參數與意義）】
{json.dumps(event_attributes, ensure_ascii=False, indent=2)}

【MCP 輸出資料樣本（診斷函式的輸入格式）】
{json.dumps(mcp_output_sample, ensure_ascii=False, indent=2)}

【使用者的異常判斷條件（Diagnostic Prompt）】
「{diagnostic_prompt}」

【使用者指定的有問題物件（Problem Subject）】
「{problem_subject or "未指定"}」

請完成以下評估並提供改善建議：

1. 異常判斷條件是否清晰（可直接轉換為 Python 邏輯）：
   - 是否明確對應到 MCP 輸出的具體欄位名稱？
   - 是否有可量化的判斷條件（數值門檻、計數、時間條件等）？
   - 是否清楚說明何時算正常、何時算異常？

2. 有問題的物件是否具體可識別：
   - 應為可從 MCP 輸出或事件屬性中找到的具體物件（如 Tool ID、Lot ID、製程參數名稱等）

改寫原則：
- 明確引用 MCP 輸出中的具體欄位名稱
- 加入具體的數值門檻或計數條件
- ⚠️ 不要在改寫版本中加入輸出格式指令（系統輸出格式固定為 diagnosis_message + problem_object）

只回傳 JSON（不要有其他文字）：
{{
  "is_clear": true 或 false,
  "questions": ["若不清晰才填，最多3個問題；若已清晰則為空陣列"],
  "suggested_prompt": "改寫後的完整診斷條件（即使原本清晰也提供更精確的版本）",
  "suggested_problem_subject": "改善後的有問題物件說明（若已合理可小幅調整或保持相同）",
  "changes": "一句話說明改寫了什麼"
}}"""

        try:
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(_get_text(response.content))
            data.setdefault("is_clear", True)
            data.setdefault("questions", [])
            data.setdefault("suggested_prompt", diagnostic_prompt)
            data.setdefault("suggested_problem_subject", problem_subject or "")
            data.setdefault("changes", "")
            return data
        except Exception:
            return {
                "is_clear": True, "questions": [],
                "suggested_prompt": diagnostic_prompt,
                "suggested_problem_subject": problem_subject or "",
                "changes": "",
            }

    async def generate_code_diagnosis(
        self,
        diagnostic_prompt: str,
        problem_subject: Optional[str],
        mcp_sample_outputs: Dict[str, Any],
        event_attributes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate Python diagnostic code and execute it.

        The generated diagnose() function returns diagnosis_message + problem_object directly.
        Returns dict with keys: success, generated_code, diagnosis_message, problem_object, error
        """
        import math
        import datetime as _dt

        event_attributes = event_attributes or []

        # ── Step 1: LLM generates diagnostic Python code ─────────────────────
        # Build a compact schema preview that mirrors the REAL runtime structure.
        # The generated diagnose() will be executed against mcp_sample_outputs which has
        # {"mcp_name": {"dataset": [...full rows...], ...}}.
        # Only send column schema + 1 example row — LLM needs field names/types only, not raw data.
        def _schema_preview(outputs: Dict[str, Any]) -> Dict[str, Any]:
            preview = {}
            for mcp_name, mcp_data in outputs.items():
                if not isinstance(mcp_data, dict):
                    preview[mcp_name] = mcp_data
                    continue
                dataset = mcp_data.get("dataset") or []
                total = len(dataset)
                if dataset:
                    example = dataset[0]
                    columns = {k: type(v).__name__ for k, v in example.items()} if isinstance(example, dict) else {}
                    preview[mcp_name] = {
                        "columns": columns,      # {field: type} — schema reference
                        "example_row": example,  # 1 row for field name/value context
                        "_total_rows": total,    # full dataset at runtime: mcp_outputs[name]["dataset"]
                    }
                else:
                    preview[mcp_name] = {"columns": {}, "example_row": {}, "_total_rows": 0}
            return preview

        mcp_schema = _schema_preview(mcp_sample_outputs)
        code_prompt = f"""你是半導體製程智能診斷工程師。請根據以下信息，撰寫一個 Python 診斷函式。

【觸發此 Skill 的事件屬性（診斷背景參考）】
{json.dumps(event_attributes, ensure_ascii=False, indent=2)}

【有問題的項目或物件】
{problem_subject or "未指定"}

【異常判斷條件（Diagnostic Prompt）】
{diagnostic_prompt}

【MCP 輸出欄位結構（columns=欄位類型, example_row=1筆範例；執行時完整資料通過 mcp_outputs[mcp_name]["dataset"] 存取）】
{json.dumps(mcp_schema, ensure_ascii=False, indent=2)}

只回傳 Python 程式碼區塊（不要有其他文字，不要包在 JSON 裡）。

⚠️ **必須**以下列樣板開頭（前兩行不可更改，這是取資料的唯一正確方式）：
```python
def diagnose(mcp_outputs: dict) -> dict:
    rows = list(mcp_outputs.values())[0].get("dataset", [])
    if not rows:
        return {{"status": "NORMAL", "diagnosis_message": "無資料", "problem_object": {{}}}}
    # 在此撰寫你的診斷邏輯
    ...
```

函式規範：
- 根據「異常判斷條件」對 rows 進行邏輯判斷（rows 是完整資料列的 list）
- 禁止使用 `mcp_name`、`mcp_outputs.keys()` 等未先定義的變數存取 key
- 函式必須回傳 dict，包含三個 key：
  - "status": "NORMAL" 或 "ABNORMAL"
    * ABNORMAL：資料符合異常條件
    * NORMAL  ：一切正常
  - "diagnosis_message": str — 繁體中文診斷訊息（2-3 句話，具體說明結果與原因）
  - "problem_object": dict — key 為物件類型（英文），value 為實際 ID 值
    ① 單一：{{"tool": "TETCH01"}}
    ② 多個：{{"tool": ["TETCH01","TETCH03"]}}
    ③ 正常時：{{}}（空 dict）
    ❌ 禁止回傳泛稱字串（必須是資料中的實際 ID 值）
- 只使用 Python 標準語法；可用 json, math, datetime, collections
- 不要使用 eval(), exec(), os, sys
- ⚠️ **Python 語法鐵律**：if/else/for/while 區塊內必須有至少一條語句，禁止空區塊。若無實際邏輯，用 `pass` 填充。
- ⚠️ **禁止在 if 條件後面直接 return 而不縮排**：if 的 body 必須縮排 4 格。
- ⚠️ **Exception Handling 鐵律**：主診斷邏輯必須包在 try/except 中，格式如下：
  ```python
  try:
      # 診斷邏輯
  except Exception as e:
      return {{"status": "ABNORMAL", "diagnosis_message": f"診斷執行異常：{{e}}", "problem_object": {{}}}}
  ```
  exception message 必須使用 `f"診斷執行異常：{{e}}"` 格式，不可自訂其他格式。"""

        # v14.2: use llm_retry + SkillCodeOutputGuard so structural errors
        # in the generated diagnose() function are caught and fed back to LLM.
        _t0_llm = time.time()
        _skill_attempt_count = [0]
        _skill_events: List[str] = []
        _skill_guard_failures = [0]

        def _extract_code(raw_text: str) -> str:
            m = re.search(r"```(?:python)?\s*([\s\S]+?)\s*```", raw_text)
            if m:
                return m.group(1).strip()
            idx = raw_text.find("def diagnose")
            return raw_text[idx:].strip() if idx != -1 else raw_text.strip()

        async def _call_skill(error_context: Optional[str]) -> str:
            retry_suffix = ""
            if error_context:
                retry_suffix = (
                    f"\n\n⚠️ 上一次生成的 diagnose() 函式有以下問題，請修正：\n{error_context}"
                )
                _skill_events.append(
                    f"[Schema Guard] 注入驗證錯誤，發起第 {_skill_attempt_count[0] + 1} 次重試…"
                )
            _skill_attempt_count[0] += 1
            resp = await self._client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": code_prompt + retry_suffix}],
            )
            return _extract_code(_get_text(resp.content))

        def _validate_skill(code: str) -> str:
            try:
                return SkillCodeOutputGuard.validate(code)
            except ValueError as exc:
                _skill_guard_failures[0] += 1
                err_short = str(exc)[:80]
                _skill_events.append(
                    f"[Schema Guard ✗] 第 {_skill_attempt_count[0]} 次驗證失敗：{err_short}"
                )
                raise

        try:
            generated_code = await llm_retry(
                _call_skill,
                _validate_skill,
                max_retries=2,
            )
        except Exception as exc:
            return {
                "success": False, "generated_code": "", "code_result": None,
                "response_message": "", "error": f"Code generation failed: {exc}",
                "llm_elapsed_s": 0.0, "exec_elapsed_s": 0.0, "input_records": 0,
                "learning_events": _skill_events,
            }
        if _skill_guard_failures[0] == 0:
            _skill_events.append(
                "[Schema Guard ✓] 診斷碼結構驗證通過（def diagnose ✓ · status/diagnosis_message/problem_object ✓）"
            )
        else:
            _skill_events.append(
                f"[Schema Guard ✓] 診斷碼驗證通過（共嘗試 {_skill_attempt_count[0]} 次，修正 {_skill_guard_failures[0]} 次失敗）"
            )
        _t1_llm = time.time()

        if not generated_code:
            return {
                "success": False, "generated_code": "", "code_result": None,
                "response_message": "", "error": "LLM did not return any code",
            }

        # ── Step 2: Execute the code safely ──────────────────────────────────
        _ALLOWED_IMPORTS = frozenset({
            "json", "math", "datetime", "collections", "itertools",
            "functools", "statistics", "re", "operator",
            "_strptime",    # implicit import triggered by datetime.strptime() on first call
            "_datetime",    # C extension backing the datetime module
        })

        def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.split(".")[0] not in _ALLOWED_IMPORTS:
                raise ImportError(f"Import of '{name}' is not allowed in diagnostic sandbox")
            return __import__(name, globals, locals, fromlist, level)

        _SAFE_BUILTINS = {
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "filter": filter, "float": float, "format": format,
            "frozenset": frozenset, "int": int, "isinstance": isinstance, "issubclass": issubclass,
            "len": len, "list": list, "map": map, "max": max, "min": min, "next": next,
            "print": print, "range": range, "repr": repr, "reversed": reversed,
            "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
            "tuple": tuple, "type": type, "zip": zip,
            "True": True, "False": False, "None": None,
            "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
            "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
            "__import__": _safe_import,
        }
        import collections as _collections
        sandbox = {
            "__builtins__": _SAFE_BUILTINS,
            "json": __import__("json"),
            "math": math,
            "datetime": _dt,
            "collections": _collections,
            "deque": _collections.deque,
            "Counter": _collections.Counter,
            "defaultdict": _collections.defaultdict,
            "OrderedDict": _collections.OrderedDict,
        }

        try:
            compile(generated_code, "<diagnose>", "exec")
        except SyntaxError as exc:
            return {
                "success": False, "generated_code": generated_code,
                "status": "ABNORMAL", "diagnosis_message": "", "problem_object": {},
                "error": f"Code syntax error: {exc}",
                "llm_elapsed_s": round(_t1_llm - _t0_llm, 2), "exec_elapsed_s": 0.0, "input_records": 0,
            }

        _t0_exec = time.time()
        try:
            exec(generated_code, sandbox)  # noqa: S102
            diagnose_fn = sandbox.get("diagnose")
            if not callable(diagnose_fn):
                return {
                    "success": False, "generated_code": generated_code, "code_result": None,
                    "response_message": "", "error": "Generated code does not define a callable 'diagnose' function",
                    "llm_elapsed_s": round(_t1_llm - _t0_llm, 2), "exec_elapsed_s": 0.0, "input_records": 0,
                }
            # Count input records for metrics
            _input_rec = 0
            for _v in mcp_sample_outputs.values():
                if isinstance(_v, dict):
                    _input_rec = len(_v.get("dataset") or [])
                    break
            raw_result = diagnose_fn(mcp_sample_outputs)
            if not isinstance(raw_result, dict):
                return {
                    "success": False, "generated_code": generated_code,
                    "diagnosis_message": "", "problem_object": "",
                    "error": f"diagnose() must return a dict, got {type(raw_result).__name__}",
                    "llm_elapsed_s": round(_t1_llm - _t0_llm, 2), "exec_elapsed_s": 0.0, "input_records": _input_rec,
                }
            raw_status        = str(raw_result.get("status", "")).upper()
            status            = "NORMAL" if raw_status == "NORMAL" else "ABNORMAL"
            diagnosis_message = str(raw_result.get("diagnosis_message", "診斷完成。"))
            # P1 fix: problem_object must be a dict — LLM sometimes returns a string or list
            problem_object = raw_result.get("problem_object", {})
            if not isinstance(problem_object, dict):
                logger.warning(
                    "generate_code_diagnosis: problem_object is %s (not dict), normalizing to {}",
                    type(problem_object).__name__,
                )
                problem_object = {}
        except Exception as exc:
            return {
                "success": False, "generated_code": generated_code,
                "status": "ABNORMAL", "diagnosis_message": "", "problem_object": {},
                "error": f"Code execution error: {exc}",
                "llm_elapsed_s": round(_t1_llm - _t0_llm, 2), "exec_elapsed_s": 0.0, "input_records": 0,
            }
        _t1_exec = time.time()

        # Build check_output_schema — status is always the first field
        # problem_object is expected to be a dict: {key: str | list[str]}
        schema_fields = [
            {"name": "status", "type": "string", "description": "NORMAL 或 ABNORMAL"},
            {"name": "diagnosis_message", "type": "string", "description": "診斷說明"},
        ]
        if isinstance(problem_object, dict) and problem_object:
            for k, v in problem_object.items():
                field_type = "array" if isinstance(v, list) else "string"
                schema_fields.append({"name": k, "type": field_type, "description": f"有問題的 {k}"})

        check_output_schema = {"fields": schema_fields}

        _skill_events.append(
            f"[Sandbox ✓] diagnose() 執行完成 → status={status}"
            + (f"（problem_object 已正規化為 {{}}）" if not isinstance(raw_result.get("problem_object"), dict) else "")
        )
        return {
            "success": True,
            "generated_code": generated_code,
            "status": status,
            "diagnosis_message": diagnosis_message,
            "problem_object": problem_object,
            "check_output_schema": check_output_schema,
            "error": None,
            "llm_elapsed_s": round(_t1_llm - _t0_llm, 2),
            "exec_elapsed_s": round(_t1_exec - _t0_exec, 2),
            "input_records": _input_rec,
            "learning_events": _skill_events,
        }

    async def auto_map(
        self,
        data_subject_inputs: list,
        event_attributes: list,
    ) -> Dict[str, Any]:
        """LLM semantic mapping: match DataSubject input fields to Event attributes.

        Args:
            data_subject_inputs: List of DS input field dicts [{name, type, description, required}]
            event_attributes:    List of Event attribute dicts [{name, type, description, required}]

        Returns:
            dict with key "mapping": [{mcp_input, mapped_event_attribute, confidence}]
        """
        prompt = f"""你是一個半導體資料工程師。請幫我將 Event 的屬性，映射到 Data Subject 的 Input 參數上。

【Data Subject 需要的 Input】：
{json.dumps(data_subject_inputs, ensure_ascii=False, indent=2)}

【Event 提供的 Attributes】：
{json.dumps(event_attributes, ensure_ascii=False, indent=2)}

請根據名稱語意（例如 "ToolID" 對應 "eqp_id"、"lotID" 對應 "lot_id"）判斷最合理的對應關係。
若無法確定，請將 mapped_event_attribute 設為 null。

只回傳 JSON，不要有其他文字：
{{
  "mapping": [
    {{
      "mcp_input": "lot_id",
      "mapped_event_attribute": "lotID",
      "confidence": "HIGH"
    }}
  ]
}}"""

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            return _extract_json(_get_text(response.content))
        except Exception:
            logger.warning("auto_map JSON parse failed, raw: %s", _get_text(response.content)[:200])
            return {"mapping": []}
