"""llm_utils.py — Lightweight LLM retry + error classification utilities.

v14.2 Self-Healing Builder:
- classify_error()  : deterministic label from Python traceback string
- llm_retry()       : generic generate → validate → retry loop

Design decisions (from Gemini + small柯 review):
- llm_retry covers ONLY the "LLM generates → format validates" path.
  Agent Tool Call errors (environment) are handled separately via write_trap().
- classify_error returns 6 labels that match the categories most useful
  for a retry prompt (tells LLM *why* its last attempt failed).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Error classifier ────────────────────────────────────────────────────────

def classify_error(error_msg: str) -> str:
    """Classify a Python sandbox / traceback string into a label.

    Returns one of:
        MISSING_COLUMN  – KeyError or column-not-found pattern
        TYPE_MISMATCH   – TypeError / most ValueErrors
        IMPORT_ERROR    – ModuleNotFoundError / ImportError
        EMPTY_DATA      – data is None / empty / not iterable
        SYNTAX_ERROR    – SyntaxError / IndentationError
        LOGIC_ERROR     – catch-all
    """
    msg = error_msg.lower()

    # MISSING_COLUMN: KeyError + any column / field hint
    if "keyerror" in msg:
        return "MISSING_COLUMN"
    if "column" in msg and any(w in msg for w in ("not found", "does not exist", "missing", "has no")):
        return "MISSING_COLUMN"

    # IMPORT_ERROR
    if "modulenotfounderror" in msg or "importerror" in msg:
        return "IMPORT_ERROR"

    # SYNTAX_ERROR
    if "syntaxerror" in msg or "indentationerror" in msg:
        return "SYNTAX_ERROR"

    # EMPTY_DATA
    if any(w in msg for w in (
        "is empty", "empty or none", "nonetype", "none is not iterable",
        "object is not iterable", "list index out of range",
    )):
        return "EMPTY_DATA"
    if "typeerror" in msg and "nonetype" in msg:
        return "EMPTY_DATA"

    # TYPE_MISMATCH
    if "typeerror" in msg or "valueerror" in msg:
        return "TYPE_MISMATCH"

    return "LOGIC_ERROR"


# ── llm_retry ────────────────────────────────────────────────────────────────

async def llm_retry(
    fn: Callable[[Optional[str]], Any],
    validator: Callable[[Any], Any],
    max_retries: int = 2,
) -> Any:
    """Generic LLM generate → validate → retry loop.

    Args:
        fn: async callable(error_context: str | None) → raw_result.
            First call receives None; retries receive the validation
            error string so the LLM can see exactly what was wrong.
        validator: callable(raw_result) → validated_result.
            Must raise ValueError (or pydantic.ValidationError) on failure.
        max_retries: number of retry attempts after the initial call.
            Total calls = 1 + max_retries.

    Returns:
        validated result.

    Raises:
        ValueError if all attempts are exhausted.
    """
    error_context: Optional[str] = None
    last_exc: Exception = ValueError("llm_retry: no attempts made")

    for attempt in range(max_retries + 1):
        try:
            result = await fn(error_context)
            return validator(result)
        except Exception as exc:
            last_exc = exc
            error_context = str(exc)
            logger.warning(
                "llm_retry attempt %d/%d failed: %s",
                attempt + 1, max_retries + 1, exc,
            )
            if attempt >= max_retries:
                break

    raise ValueError(f"LLM retry 失敗（共 {max_retries + 1} 次）：{last_exc}")
