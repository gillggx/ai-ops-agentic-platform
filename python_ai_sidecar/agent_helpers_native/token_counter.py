"""token_counter.py — count_tokens(text) and tokens_of_messages helpers.

Spec: docs/SPEC_context_engineering_phase2 §1.C.

Strategy:
  1. Prefer tiktoken (cl100k_base) — fast, offline, ~5% error vs Anthropic
     real tokenization for mixed CJK + English.
  2. Fall back to a CJK-aware char heuristic when tiktoken is missing
     (3.5 chars/token for ASCII, 1.5 chars/token for CJK).

We deliberately do NOT call the Anthropic `/v1/messages/count_tokens`
endpoint here — it adds 200-500ms per check and would defeat the purpose
of cheap budget gating. If precise counts are needed (e.g. for billing
audits), call the Anthropic SDK separately.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_ENC = None
_ENC_TRIED = False


def _get_enc():
    global _ENC, _ENC_TRIED
    if _ENC_TRIED:
        return _ENC
    _ENC_TRIED = True
    try:
        import tiktoken  # type: ignore
        _ENC = tiktoken.get_encoding("cl100k_base")
        logger.info("token_counter: tiktoken cl100k_base loaded")
    except Exception as e:  # noqa: BLE001
        logger.warning("token_counter: tiktoken unavailable (%s) — falling back to heuristic", e)
        _ENC = None
    return _ENC


def _heuristic_count(text: str) -> int:
    """Mixed CJK + ASCII heuristic. Empirically within ~10% of Anthropic
    tokens for typical chat / catalog content. Good enough for budget gating."""
    if not text:
        return 0
    cjk = 0
    for ch in text:
        # Coarse CJK range covers Chinese / Japanese / Korean common ideographs.
        if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af":
            cjk += 1
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 3.5) + 1


def count_tokens(text: str) -> int:
    """Return an approximate token count for `text` against Sonnet 4
    tokenization. Uses tiktoken when available, heuristic otherwise."""
    if not text:
        return 0
    enc = _get_enc()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001
            return _heuristic_count(text)
    return _heuristic_count(text)


def tokens_of_messages(messages: Iterable[Any]) -> int:
    """Sum tokens across heterogeneous messages.

    Accepts:
      - LangChain BaseMessage subclasses (HumanMessage / AIMessage / ...)
      - Anthropic-style {"role": ..., "content": str | list[dict]} dicts
      - Plain strings

    Adds a small overhead per message (~4 tokens) for role tag + delimiters.
    """
    total = 0
    for m in messages:
        total += 4
        if isinstance(m, str):
            total += count_tokens(m)
            continue
        if isinstance(m, dict):
            content = m.get("content", "")
            if isinstance(content, str):
                total += count_tokens(content)
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict):
                        if blk.get("type") == "text":
                            total += count_tokens(blk.get("text", "") or "")
                        elif blk.get("type") == "tool_use":
                            import json as _json
                            total += count_tokens(blk.get("name", "") or "")
                            total += count_tokens(_json.dumps(blk.get("input") or {}, ensure_ascii=False))
                        elif blk.get("type") == "tool_result":
                            inner = blk.get("content", "")
                            if isinstance(inner, str):
                                total += count_tokens(inner)
                            else:
                                import json as _json
                                total += count_tokens(_json.dumps(inner, ensure_ascii=False))
            continue
        # LangChain BaseMessage shaped: has .content + .type
        content = getattr(m, "content", None)
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    total += count_tokens(blk.get("text", "") or "")
        # Tool calls on AIMessage
        tcs = getattr(m, "tool_calls", None)
        if tcs:
            import json as _json
            for tc in tcs:
                total += count_tokens(getattr(tc, "name", None) or tc.get("name", "") if isinstance(tc, dict) else "")
                args = getattr(tc, "args", None) or (tc.get("args") if isinstance(tc, dict) else None) or {}
                total += count_tokens(_json.dumps(args, ensure_ascii=False))
    return total
