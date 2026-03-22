"""Mock Data Studio Service — sandbox execution + LLM code generation for mock data sources."""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.services.sandbox_service import _static_check, _make_json_serializable
from app.utils.llm_client import get_llm_client

_GENERATE_ALLOWED_MODULES = frozenset({
    "json", "math", "statistics", "datetime", "collections",
    "itertools", "functools", "operator", "re", "string", "decimal",
    "io", "base64", "copy", "random", "time", "calendar", "hashlib",
    "_strptime", "_decimal", "_json", "_datetime", "_collections_abc",
    "_functools", "_operator", "_io", "_statistics", "_heapq", "_bisect",
    "_struct", "_csv", "_abc", "_hashlib",
})


def _generate_safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    base = name.split(".")[0]
    if base not in _GENERATE_ALLOWED_MODULES and name not in _GENERATE_ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not allowed in generate sandbox.")
    import importlib
    return importlib.import_module(name)


logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

# Uses section markers so Python code is NEVER embedded inside JSON strings.
_GENERATE_SYSTEM_PROMPT = """\
你是一個 Mock Data Studio 專家，專門為半導體製程 Demo 環境撰寫 Python 模擬資料產生器。

你的任務：根據使用者描述，撰寫一個 Python 函式 `generate(params: dict) -> list`。

規則：
1. 函式名稱固定為 `generate`，參數為 `params: dict`，回傳 `list`（不可回傳 dict）
2. 使用 hash-seed 技術讓相同 params 每次回傳相同資料（確定性模擬）
3. 資料要有半導體工廠真實感：lot_id 格式 L26xxxxx、tool 格式 TETCH01、時間 ISO 8601
4. 禁止 import requests, urllib, socket, subprocess, os, sys
5. 允許的 import：math, json, datetime, random, collections, statistics, re
6. 包含 3~5 個異常資料點（超出 UCL/LCL 或其他異常標記）
7. 資料量需符合描述（若描述說 1000 筆，生成 1000 筆）

回應格式（嚴格按此結構，使用 section marker 分隔各部分）：

===INPUT_SCHEMA===
{"fields": [{"name": "...", "type": "string|number|boolean", "description": "...", "required": true}]}
===PYTHON_CODE===
def generate(params: dict) -> list:
    # your implementation
    ...
===SAMPLE_PARAMS===
{"param_name": "example_value"}
===END===
"""

_QUICK_SAMPLE_SYSTEM_PROMPT = """\
你是半導體製程資料模擬專家。根據使用者的描述，直接生成符合格式的 JSON 假資料。

規則：
1. 直接回傳 JSON 陣列（list of dicts），不需要程式碼
2. 生成 {count} 筆資料
3. 資料要有半導體工廠真實感：lot_id 格式 L26xxxxx、tool TETCH01、時間 ISO 8601
4. 若描述中有 UCL/LCL，讓 3~5 筆超出管制界限
5. 只回傳 JSON array，不要 markdown fence，不要說明文字
"""


# ── Sandbox ───────────────────────────────────────────────────────────────────

def _run_generate_sync(code: str, params: Dict[str, Any]) -> Any:
    """Execute the generate(params) function in sandbox and return its result."""
    import base64
    import collections
    import datetime
    import functools
    import hashlib
    import io
    import itertools
    import math
    import random
    import re as re_mod
    import statistics

    safe_builtins: Dict[str, Any] = {
        "abs": abs, "all": all, "any": any, "bool": bool,
        "dict": dict, "enumerate": enumerate, "filter": filter,
        "float": float, "int": int, "isinstance": isinstance,
        "issubclass": issubclass, "iter": iter, "len": len,
        "list": list, "map": map, "max": max, "min": min,
        "next": next, "range": range, "repr": repr, "reversed": reversed,
        "round": round, "set": set, "slice": slice, "sorted": sorted,
        "str": str, "sum": sum, "tuple": tuple, "type": type, "zip": zip,
        "print": print, "hash": hash, "id": id,
        "getattr": getattr, "hasattr": hasattr, "setattr": setattr,
        "format": format, "vars": vars, "dir": dir,
        "chr": chr, "ord": ord, "hex": hex, "oct": oct, "bin": bin,
        "bytes": bytes, "bytearray": bytearray,
        "frozenset": frozenset, "complex": complex,
        "divmod": divmod, "pow": pow,
        "object": object,
        "None": None, "True": True, "False": False,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "RuntimeError": RuntimeError, "StopIteration": StopIteration,
        "__import__": _generate_safe_import,
    }

    global_ns: Dict[str, Any] = {
        "__builtins__": safe_builtins,
        "json": __import__("json"),
        "math": math,
        "statistics": statistics,
        "datetime": datetime,
        "collections": collections,
        "itertools": itertools,
        "functools": functools,
        "random": random,
        "hashlib": hashlib,
        "re": re_mod,
        "io": io,
        "base64": base64,
        "deque": collections.deque,
        "Counter": collections.Counter,
        "defaultdict": collections.defaultdict,
    }

    exec(compile(code, "<mock_generate>", "exec"), global_ns)  # noqa: S102

    generate_fn = global_ns.get("generate")
    if not callable(generate_fn):
        raise ValueError("Code must define a callable `generate(params: dict) -> list` function.")

    result = generate_fn(params)
    if not isinstance(result, (list, dict)):
        raise ValueError(f"generate() must return a list or dict, got {type(result).__name__}.")

    return _make_json_serializable(result)


async def execute_generate_fn(
    code: str,
    params: Dict[str, Any],
    timeout: float = 10.0,
) -> Any:
    """Execute mock data source generate(params) in sandbox."""
    _static_check(code)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_generate_sync, code, params),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"generate() timed out after {timeout:.0f}s.")
    return result


# ── Section parser ────────────────────────────────────────────────────────────

def _parse_sections(text: str) -> Dict[str, str]:
    """Parse LLM response with ===SECTION=== markers.

    Returns dict with keys: INPUT_SCHEMA, PYTHON_CODE, SAMPLE_PARAMS.
    Falls back gracefully if sections are missing.
    """
    sections: Dict[str, str] = {}
    pattern = re.compile(r"===([A-Z_]+)===\s*([\s\S]*?)(?====|$)")
    for m in pattern.finditer(text):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key != "END":
            sections[key] = val
    return sections


# ── Service ───────────────────────────────────────────────────────────────────

class MockDataStudioService:
    """LLM-powered code generator and sample data generator for Mock Data Studio."""

    def __init__(self) -> None:
        self._llm = get_llm_client()

    async def generate_code(
        self,
        description: str,
        input_schema: Optional[str] = None,
        sample_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ask Claude to generate a mock data source Python function.

        Uses section markers to avoid JSON-escaping issues with Python code.
        Returns dict: {input_schema, python_code, sample_params}.
        """
        user_msg = f"請為以下描述建立 Mock Data Source：\n\n{description}"
        if input_schema:
            user_msg += f"\n\n已知 input_schema：\n{input_schema}"
        if sample_params:
            user_msg += f"\n\n範例呼叫參數：{json.dumps(sample_params, ensure_ascii=False)}"

        response = await asyncio.wait_for(
            self._llm.create(
                system=_GENERATE_SYSTEM_PROMPT,
                max_tokens=4096,
                messages=[{"role": "user", "content": user_msg}],
            ),
            timeout=55.0,
        )

        text = response.text.strip()
        logger.debug("generate_code LLM raw response length=%d", len(text))

        sections = _parse_sections(text)

        # Parse input_schema JSON safely
        schema_val: Optional[Dict[str, Any]] = None
        if "INPUT_SCHEMA" in sections:
            try:
                schema_val = json.loads(sections["INPUT_SCHEMA"])
            except json.JSONDecodeError:
                logger.warning("Failed to parse INPUT_SCHEMA JSON, keeping raw string")

        # Parse sample_params JSON safely
        sp_val: Dict[str, Any] = {}
        if "SAMPLE_PARAMS" in sections:
            try:
                sp_val = json.loads(sections["SAMPLE_PARAMS"])
            except json.JSONDecodeError:
                logger.warning("Failed to parse SAMPLE_PARAMS JSON")

        python_code = sections.get("PYTHON_CODE", "")

        # Fallback: try to extract python code from ```python block
        if not python_code:
            m = re.search(r"```python\s*([\s\S]+?)```", text)
            if m:
                python_code = m.group(1).strip()

        return {
            "input_schema": schema_val,
            "python_code": python_code,
            "sample_params": sp_val,
        }

    async def quick_sample(
        self,
        description: str,
        count: int = 20,
    ) -> List[Dict[str, Any]]:
        """Ask Claude to generate N sample data rows directly as JSON (no Python code).

        Returns a list of dicts ready for display.
        """
        system = _QUICK_SAMPLE_SYSTEM_PROMPT.replace("{count}", str(count))
        user_msg = f"描述：{description}\n\n請生成 {count} 筆資料。"

        # For complex descriptions (many fields), cap at 5 rows to avoid token overflow
        effective_count = count
        complexity_hints = ["30個", "30+", "超過", "parameters", "30 個", "多個欄位", "many"]
        if any(h in description for h in complexity_hints) and count > 5:
            effective_count = 5
            logger.info("quick_sample: complex description detected, capping count %d→5", count)

        system_with_count = _QUICK_SAMPLE_SYSTEM_PROMPT.replace("{count}", str(effective_count))
        user_msg_final = f"描述：{description}\n\n請生成 {effective_count} 筆資料。"

        async def _call_llm(n: int) -> str:
            prompt = _QUICK_SAMPLE_SYSTEM_PROMPT.replace("{count}", str(n))
            msg = f"描述：{description}\n\n請生成 {n} 筆資料。"
            resp = await asyncio.wait_for(
                self._llm.create(
                    system=prompt,
                    max_tokens=8192,
                    messages=[{"role": "user", "content": msg}],
                ),
                timeout=50.0,  # fail before nginx 60s gateway timeout
            )
            raw = resp.text.strip()
            logger.info("quick_sample LLM stop_reason=%s len=%d count=%d", resp.stop_reason, len(raw), n)
            return raw

        def _parse(text: str) -> List[Dict[str, Any]]:
            t = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            t = re.sub(r"\s*```\s*$", "", t, flags=re.MULTILINE).strip()
            try:
                data = json.loads(t)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return [data]
            except json.JSONDecodeError:
                m = re.search(r"\[[\s\S]+\]", t)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except json.JSONDecodeError:
                        pass
            return []

        # First attempt
        text = await _call_llm(effective_count)
        rows = _parse(text)

        # Retry with 3 rows if first attempt produced no valid JSON
        if not rows and effective_count > 3:
            logger.warning("quick_sample: first attempt failed, retrying with 3 rows")
            text = await _call_llm(3)
            rows = _parse(text)

        if not rows:
            logger.error("quick_sample: could not parse LLM response as JSON, raw=%s", text[:300])
            raise ValueError("LLM 未回傳有效 JSON 陣列，請重試")

        return rows
