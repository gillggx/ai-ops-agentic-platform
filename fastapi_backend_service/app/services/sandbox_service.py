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
    "pandas", "plotly", "matplotlib",
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
    r"^[ \t]*(import\s+(plotly|pandas|matplotlib)\b[^\n]*"
    r"|from\s+(plotly|pandas|matplotlib)\b[^\n]*)[ \t]*$",
    re.MULTILINE,
)


def _strip_preinjected_imports(script: str) -> str:
    """Remove import lines for pre-injected libs; they're already in global_ns."""
    return _PREINJECTED_IMPORT_RE.sub("# [auto-removed: pre-injected]", script)


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

    local_ns: Dict[str, Any] = {}

    clean_script = _strip_preinjected_imports(script)
    exec(compile(clean_script, "<mcp_script>", "exec"), global_ns, local_ns)  # noqa: S102

    process_fn = local_ns.get("process")
    if not callable(process_fn):
        raise ValueError(
            "Script must define a callable `process(raw_data: dict) -> dict` function."
        )

    result = process_fn(raw_data)
    if not isinstance(result, dict):
        raise ValueError(
            f"process() must return a dict, got {type(result).__name__}."
        )
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
