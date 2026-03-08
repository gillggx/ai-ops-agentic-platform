"""Mock Data Studio Service — sandbox execution + LLM code generation for mock data sources."""

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

import anthropic

from app.config import get_settings
from app.services.sandbox_service import _static_check, _make_json_serializable

_GENERATE_ALLOWED_MODULES = frozenset({
    "json", "math", "statistics", "datetime", "collections",
    "itertools", "functools", "operator", "re", "string", "decimal",
    "io", "base64", "copy", "random", "time", "calendar",
    "_strptime", "_decimal", "_json", "_datetime", "_collections_abc",
    "_functools", "_operator", "_io", "_statistics", "_heapq", "_bisect",
    "_struct", "_csv", "_abc",
})


def _generate_safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    base = name.split(".")[0]
    if base not in _GENERATE_ALLOWED_MODULES and name not in _GENERATE_ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not allowed in generate sandbox.")
    import importlib
    return importlib.import_module(name)

logger = logging.getLogger(__name__)
_MODEL = get_settings().LLM_MODEL

_GENERATE_SYSTEM_PROMPT = """\
你是一個 Mock Data Studio 專家，專門為半導體製程 Demo 環境撰寫 Python 模擬資料產生器。

你的任務：根據使用者描述，撰寫一個 Python 函式 `generate(params: dict) -> list`，
該函式接收查詢參數，回傳符合真實製程格式的模擬 list of dicts（類似 REST API 的 JSON 陣列回應）。

規則：
1. 函式名稱固定為 `generate`，參數為 `params: dict`，回傳 `list`（不可回傳 dict）
2. 使用 hash-seed 技術讓相同 params 每次回傳相同資料（確定性模擬）
3. 資料要有半導體工廠的真實感：lot_id 格式 L26xxxxx、tool_id 格式 TECHxx、時間用 ISO 8601
4. 禁止 import requests, urllib, socket, subprocess, os, sys；只能用 math, json, datetime, random, collections
5. 包含 3~5 個異常資料點（模擬真實工廠偶發異常）
6. 回傳純 JSON 格式（不要 markdown fence），結構：
{
  "input_schema": {"fields": [{"name": str, "type": str, "description": str, "required": bool}]},
  "python_code": "def generate(params: dict) -> list:\\n    ...",
  "sample_params": {"key": "value", ...}
}
"""


def _run_generate_sync(code: str, params: Dict[str, Any]) -> Any:
    """Execute the generate(params) function in sandbox and return its result."""
    import base64
    import collections
    import datetime
    import functools
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
        "re": re_mod,
        "io": io,
        "base64": base64,
    }

    local_ns: Dict[str, Any] = {}
    exec(compile(code, "<mock_generate>", "exec"), global_ns, local_ns)  # noqa: S102

    generate_fn = local_ns.get("generate")
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
    """Execute mock data source generate(params) in sandbox.

    Returns: list or dict — the raw response from the generate() function.
    """
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


class MockDataStudioService:
    """LLM-powered code generator for Mock Data Studio."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=get_settings().ANTHROPIC_API_KEY)

    async def generate_code(
        self,
        description: str,
        input_schema: Optional[str] = None,
        sample_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ask Claude to generate a mock data source Python function.

        Returns dict with keys: input_schema, python_code, sample_params.
        """
        user_msg = f"請為以下描述建立 Mock Data Source：\n\n{description}"
        if input_schema:
            user_msg += f"\n\n已知 input_schema：\n{input_schema}"
        if sample_params:
            user_msg += f"\n\n範例呼叫參數：{json.dumps(sample_params, ensure_ascii=False)}"

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.messages.create(
                model=_MODEL,
                max_tokens=2048,
                system=_GENERATE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ),
        )

        text = response.content[0].text.strip()

        # Strip markdown fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON object
            m = re.search(r"\{[\s\S]+\}", text)
            if m:
                result = json.loads(m.group(0))
            else:
                raise ValueError(f"LLM returned non-JSON response: {text[:200]}")

        return {
            "input_schema": result.get("input_schema"),
            "python_code": result.get("python_code", ""),
            "sample_params": result.get("sample_params", {}),
        }
