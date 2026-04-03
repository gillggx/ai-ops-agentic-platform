"""Sandbox execution service for LLM-generated Python scripts.

Executes a ``process(raw_data: dict) -> dict`` function from a script string
in a restricted namespace with a configurable timeout.

Security model:
- Restricted __builtins__: no open(), eval(), exec(), import of dangerous modules
- Allow-list of safe stdlib modules + approved data/viz libraries
- Hard 10-second execution timeout via asyncio + thread executor
- Static pattern scan for obvious forbidden constructs
"""

import asyncio
import base64
import collections
import datetime
import functools
import io
import itertools
import json
import logging
import math
import re
import statistics
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── Optional heavy dependencies (injected if installed) ──────────────────────
try:
    import pandas as _pd
except ImportError:
    _pd = None

try:
    import plotly
    import plotly.graph_objects as _go
    import plotly.express as _px
except ImportError:
    plotly = None
    _go = None
    _px = None

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend (no display needed)
    import matplotlib.pyplot as _plt
except ImportError:
    _plt = None

try:
    import numpy as _np
except ImportError:
    _np = None

# ── Generic Tools namespace (pre-built at module load; injected as `tools`) ──
try:
    from types import SimpleNamespace as _SimpleNamespace
    from app.generic_tools import TOOL_REGISTRY as _TOOL_REGISTRY
    _tools_ns = _SimpleNamespace(**{name: entry["fn"] for name, entry in _TOOL_REGISTRY.items()})
except Exception:
    _tools_ns = None

# Modules the generated script is allowed to import (base module names).
# Includes CPython internal C-extension modules (_strptime, _decimal, …) that
# are lazily auto-imported the first time a stdlib function is called — e.g.
# `datetime.strptime()` triggers an implicit `import _strptime` on first use.
_ALLOWED_BASE_MODULES = frozenset({
    # ── User-facing stdlib modules ────────────────────────────────
    "json", "math", "statistics", "datetime", "collections",
    "itertools", "functools", "operator", "re", "string", "decimal",
    "io", "base64", "copy", "abc", "numbers", "types", "enum",
    "typing", "warnings", "heapq", "bisect", "struct", "csv",
    "time", "calendar",      # pandas internal deps (pd.to_datetime / date math)
    # ── Approved data / viz libraries ────────────────────────────
    "numpy", "pandas", "plotly", "matplotlib",
    # ── CPython C-extension internals auto-imported by the above ──
    # These are private helper modules (_xyz) that CPython imports
    # transparently when you call a stdlib function for the first time.
    # They carry no network / filesystem / subprocess capability.
    "_strptime",         # datetime.strptime()  (lazy import on 1st call)
    "_decimal",          # decimal C backend
    "_json",             # json C backend
    "_datetime",         # datetime C backend
    "_collections_abc",  # collections.abc
    "_functools",        # functools C backend
    "_operator",         # operator C backend
    "_io",               # io C backend
    "_statistics",       # statistics C backend
    "_heapq",            # heapq C backend
    "_bisect",           # bisect C backend
    "_struct",           # struct C backend
    "_csv",              # csv C backend
    "_abc",              # abc C backend
})

# Regex to strip import statements for pre-injected libs (go/pd/px/plt/matplotlib).
# These are already in global_ns — re-importing them can cause conflicts on some
# Python versions (especially Python 3.14 + plotly's lazy-loading __init__).
_PREINJECTED_IMPORT_RE = re.compile(
    r"^[ \t]*(import\s+(plotly|pandas|matplotlib|numpy)\b[^\n]*"
    r"|from\s+(plotly|pandas|matplotlib|numpy)\b[^\n]*)[ \t]*$",
    re.MULTILINE,
)


def _strip_preinjected_imports(script: str) -> str:
    """Remove import lines for pre-injected libs; they're already in global_ns."""
    return _PREINJECTED_IMPORT_RE.sub("# [auto-removed: pre-injected]", script)


# Regex to intercept fig.to_html(...) — LLMs frequently call this despite prompt rules.
# Rewrite to fig.to_json() which uses Plotly's own encoder and handles pandas Timestamps,
# numpy types, and other non-serialisable objects natively.
# NOTE: we do NOT rewrite fig.to_json() — it is already the correct format.
_TO_HTML_RE = re.compile(
    r"\b([a-zA-Z_]\w*)\.to_html\s*\([^)]*\)"
)


def _rewrite_plotly_output(script: str) -> str:
    """Rewrite fig.to_html(...) → fig.to_json() so LLM-generated scripts
    always produce Plotly JSON chart data even when they call to_html().

    Uses fig.to_json() (not json.dumps(fig.to_dict())) because Plotly's own
    JSON encoder correctly handles pandas Timestamps and numpy types that
    Python's standard json.dumps would reject with TypeError."""
    rewritten = _TO_HTML_RE.sub(
        lambda m: f"{m.group(1)}.to_json()", script
    )
    if rewritten != script:
        logger.warning(
            "sandbox: rewrote fig.to_html() → fig.to_json()"
        )
    return rewritten


# Regex patterns that must not appear in a submitted script
_FORBIDDEN_PATTERNS = [
    r"\bimport\s+(requests?|http|urllib|socket|subprocess|os|sys|pathlib|shutil|glob|pickle)\b",
    r"\bfrom\s+(requests?|http|urllib|socket|subprocess|os|sys|pathlib|shutil)\b",
    r"\b__import__\s*\(",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bopen\s*\(",
    r"\bcompile\s*\(",
    r"\b__builtins__\b",
    r"\bos\.\w+",
    r"\bsys\.\w+",
    r"\bsubprocess\.\w+",
]


def _static_check(script: str) -> None:
    """Raise ValueError if the script contains any forbidden patterns."""
    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, script):
            raise ValueError(
                f"Script 包含違禁操作 (forbidden pattern: {pattern!r}). "
                "生成的腳本只能進行資料計算，不得發起網路請求或系統呼叫。"
            )


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """Allow-list based __import__ replacement injected into script namespace."""
    base = name.split(".")[0]
    if base not in _ALLOWED_BASE_MODULES and name not in _ALLOWED_BASE_MODULES:
        raise ImportError(
            f"Import of '{name}' is not allowed. "
            f"Allowed base modules: {sorted(_ALLOWED_BASE_MODULES)}"
        )
    import importlib
    return importlib.import_module(name)


def _make_json_serializable(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable objects to their JSON-safe equivalents.

    Handles the most common types produced by pandas/numpy inside sandbox scripts:
    - pd.Timestamp / datetime.datetime / datetime.date → ISO 8601 string
    - pd.NaT / pd.NA / float nan → None
    - numpy integer/floating scalars → int / float
    - numpy ndarray / pandas Series → list
    - pandas DataFrame → list of row dicts
    """
    # pandas Timestamp / NaT
    if _pd is not None:
        if isinstance(obj, _pd.Timestamp):
            return obj.isoformat() if not _pd.isnull(obj) else None
        if obj is _pd.NaT:
            return None
        try:
            if _pd.isna(obj) and not isinstance(obj, (list, dict)):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(obj, _pd.DataFrame):
            return [_make_json_serializable(r) for r in obj.to_dict(orient="records")]
        if isinstance(obj, _pd.Series):
            return [_make_json_serializable(v) for v in obj.tolist()]

    # stdlib datetime
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()

    # numpy scalars / arrays (duck-typed to avoid hard numpy dependency)
    t = type(obj)
    tmod = getattr(t, "__module__", "")
    if tmod and tmod.startswith("numpy"):
        if hasattr(obj, "tolist"):
            return obj.tolist()

    # containers — recurse
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]

    return obj


def _run_sync(script: str, raw_data: Any) -> Dict[str, Any]:
    """Execute the script synchronously in a restricted namespace."""
    safe_builtins: Dict[str, Any] = {
        # ── Core functions ────────────────────────────────────────
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
        "bytes": bytes, "bytearray": bytearray, "memoryview": memoryview,
        "frozenset": frozenset, "complex": complex,
        "divmod": divmod, "pow": pow,
        "object": object, "property": property,
        "staticmethod": staticmethod, "classmethod": classmethod,
        "super": super,
        "__import__": _safe_import,
        "None": None, "True": True, "False": False,
        # ── Exception classes (all standard built-in exceptions) ──
        "Exception": Exception, "BaseException": BaseException,
        "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "AttributeError": AttributeError, "RuntimeError": RuntimeError,
        "StopIteration": StopIteration, "NameError": NameError,
        "NotImplementedError": NotImplementedError,
        "ZeroDivisionError": ZeroDivisionError,
        "OverflowError": OverflowError, "ArithmeticError": ArithmeticError,
        "ImportError": ImportError, "ModuleNotFoundError": ModuleNotFoundError,
        "LookupError": LookupError, "AssertionError": AssertionError,
        "GeneratorExit": GeneratorExit,
    }

    global_ns: Dict[str, Any] = {
        "__builtins__": safe_builtins,
        # stdlib
        "json": json,
        "math": math,
        "statistics": statistics,
        "datetime": datetime,
        "collections": collections,
        "OrderedDict": collections.OrderedDict,
        "defaultdict": collections.defaultdict,
        "Counter": collections.Counter,
        "namedtuple": collections.namedtuple,
        "deque": collections.deque,
        "itertools": itertools,
        "functools": functools,
        "io": io,
        "base64": base64,
    }

    # Inject optional heavy libs with their conventional aliases
    if _pd is not None:
        global_ns["pandas"] = _pd
        global_ns["pd"] = _pd
    if _go is not None:
        global_ns["go"] = _go
        global_ns["plotly"] = plotly
        global_ns["px"] = _px
    if _plt is not None:
        global_ns["plt"] = _plt
        global_ns["matplotlib"] = matplotlib
    if _np is not None:
        global_ns["np"] = _np
        global_ns["numpy"] = _np

    # [v15.6] Inject analysis_library.run_analysis so template-based processing_scripts
    # can call run_analysis(template, df, params) without any sys/os imports
    try:
        from app.services.analysis_library import run_analysis as _run_analysis
        global_ns["run_analysis"] = _run_analysis
    except Exception:
        pass

    # Inject generic_tools as `tools` namespace (100+ analytic + viz functions)
    if _tools_ns is not None:
        global_ns["tools"] = _tools_ns

    # JSON-compat aliases: scripts generated via json.dumps may contain null/true/false
    global_ns["null"]  = None
    global_ns["true"]  = True
    global_ns["false"] = False

    # [P2 v15] Pre-inject raw_data as `df` so LLM scripts can operate on df directly
    # (no pd.read_csv() file I/O needed)
    if _pd is not None:
        try:
            if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict):
                global_ns["df"] = _pd.DataFrame(raw_data)
            elif isinstance(raw_data, dict):
                for _v in raw_data.values():
                    if isinstance(_v, list) and _v and isinstance(_v[0], dict):
                        global_ns["df"] = _pd.DataFrame(_v)
                        break
        except Exception:
            pass  # non-blocking: df injection is best-effort

    local_ns: Dict[str, Any] = {}

    clean_script = _rewrite_plotly_output(_strip_preinjected_imports(script))
    exec(compile(clean_script, "<mcp_script>", "exec"), global_ns, local_ns)  # noqa: S102

    process_fn = local_ns.get("process")
    if not callable(process_fn):
        raise ValueError(
            "Script must define a callable `process(raw_data: dict) -> dict` function."
        )

    try:
        result = process_fn(raw_data)
    except KeyError as exc:
        # Provide helpful context: include available keys from raw_data
        sample = raw_data[0] if isinstance(raw_data, list) and raw_data else raw_data
        available = list(sample.keys()) if isinstance(sample, dict) else []
        raise KeyError(
            f"{exc} — 腳本中使用了不存在的欄位名。資料實際可用欄位：{available}"
        ) from exc

    if not isinstance(result, dict):
        raise ValueError(
            f"process() must return a dict, got {type(result).__name__}."
        )
    # Sanitize: convert pandas Timestamps, numpy types, etc. to JSON-safe equivalents
    return _make_json_serializable(result)


def _run_diagnose_sync(code: str, mcp_outputs: Dict[str, Any]) -> Dict[str, Any]:
    """Execute diagnose(mcp_outputs) in a restricted sandbox namespace."""
    safe_builtins: Dict[str, Any] = {
        # ── Core functions ────────────────────────────────────────
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
        "bytes": bytes, "bytearray": bytearray, "memoryview": memoryview,
        "frozenset": frozenset, "complex": complex,
        "divmod": divmod, "pow": pow,
        "object": object, "property": property,
        "staticmethod": staticmethod, "classmethod": classmethod,
        "super": super,
        "__import__": _safe_import,
        "None": None, "True": True, "False": False,
        # ── Exception classes ──────────────────────────────────────
        "Exception": Exception, "BaseException": BaseException,
        "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "AttributeError": AttributeError, "RuntimeError": RuntimeError,
        "StopIteration": StopIteration, "NameError": NameError,
        "NotImplementedError": NotImplementedError,
        "ZeroDivisionError": ZeroDivisionError,
        "OverflowError": OverflowError, "ArithmeticError": ArithmeticError,
        "ImportError": ImportError, "ModuleNotFoundError": ModuleNotFoundError,
        "LookupError": LookupError, "AssertionError": AssertionError,
        "GeneratorExit": GeneratorExit,
    }

    global_ns: Dict[str, Any] = {
        "__builtins__": safe_builtins,
        "json": json,
        "math": math,
        "statistics": statistics,
        "datetime": datetime,
        "collections": collections,
        "OrderedDict": collections.OrderedDict,
        "defaultdict": collections.defaultdict,
        "Counter": collections.Counter,
        "namedtuple": collections.namedtuple,
        "deque": collections.deque,
        "itertools": itertools,
        "functools": functools,
        "io": io,
        "base64": base64,
    }

    if _pd is not None:
        global_ns["pandas"] = _pd
        global_ns["pd"] = _pd
    if _go is not None:
        global_ns["go"] = _go
        global_ns["plotly"] = plotly
        global_ns["px"] = _px
    if _plt is not None:
        global_ns["plt"] = _plt
        global_ns["matplotlib"] = matplotlib
    if _tools_ns is not None:
        global_ns["tools"] = _tools_ns

    local_ns: Dict[str, Any] = {}

    clean_code = _rewrite_plotly_output(_strip_preinjected_imports(code))
    exec(compile(clean_code, "<diagnose_script>", "exec"), global_ns, local_ns)  # noqa: S102

    diagnose_fn = local_ns.get("diagnose")
    if not callable(diagnose_fn):
        raise ValueError(
            "Diagnostic script must define a callable `diagnose(mcp_outputs: dict) -> dict` function."
        )

    result = diagnose_fn(mcp_outputs)
    if not isinstance(result, dict):
        raise ValueError(
            f"diagnose() must return a dict, got {type(result).__name__}."
        )
    # Validate required keys
    for key in ("status", "diagnosis_message", "problem_object"):
        if key not in result:
            raise ValueError(f"diagnose() result is missing required key '{key}'.")
    return result


async def execute_diagnose_fn(
    code: str,
    mcp_outputs: Dict[str, Any],
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Execute *code* with *mcp_outputs* in a sandboxed thread, with *timeout* seconds.

    Args:
        code: Python source that defines ``diagnose(mcp_outputs: dict) -> dict``.
        mcp_outputs: The MCP final dataset to pass into ``diagnose()``.
        timeout: Maximum wall-clock seconds before raising ``TimeoutError``.

    Returns:
        The dict returned by ``diagnose(mcp_outputs)`` with keys:
        ``{status, diagnosis_message, problem_object}``.

    Raises:
        ValueError: Forbidden pattern, no ``diagnose`` function, wrong return type,
                    or missing required keys.
        TimeoutError: Execution exceeded *timeout* seconds.
    """
    _static_check(code)

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_diagnose_sync, code, mcp_outputs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Diagnose script execution timed out after {timeout:.0f}s. "
            "Please simplify the diagnostic logic."
        )
    logger.debug("diagnose sandbox succeeded, status=%s", result.get("status"))
    return result


async def execute_script(
    script: str,
    raw_data: Any,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Execute *script* with *raw_data* in a sandboxed thread, with *timeout* seconds.

    Args:
        script: Python source that defines ``process(raw_data: dict) -> dict``.
        raw_data: The dataset dict to pass into ``process()``.
        timeout: Maximum wall-clock seconds before raising ``TimeoutError``.

    Returns:
        The dict returned by ``process(raw_data)``.

    Raises:
        ValueError: Forbidden pattern found, no ``process`` function, or wrong return type.
        TimeoutError: Execution exceeded *timeout* seconds.
    """
    _static_check(script)

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_sync, script, raw_data),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Script execution timed out after {timeout:.0f}s. "
            "Please simplify the processing logic."
        )
    logger.debug("sandbox execution succeeded, result keys=%s", list(result.keys()))
    return result
