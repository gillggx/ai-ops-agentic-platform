"""Node 2 — extract structured parameters (block names / use-case keywords)
from the user message. Each extractor is bucket-specific.

LLM call is haiku-class (fast, cheap, schema-constrained). The output is
NOT free-form — we parse JSON and reject non-conformant responses.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


# Block names start with `block_` by repo convention. The extractor LLM
# is told to output canonical names; this regex is a sanity validator
# AND a heuristic shortcut when the user clearly typed a name verbatim.
_BLOCK_NAME_RE = re.compile(r"\bblock_[a-z][a-z0-9_]*\b")


def _local_extract_block_names(text: str) -> list[str]:
    """Pull `block_xxx`-shaped tokens out of free text. Cheap pre-pass so
    we don't burn an LLM call when the user typed names verbatim."""
    return list(dict.fromkeys(_BLOCK_NAME_RE.findall(text)))  # de-dup, preserve order


# ── EXPLAIN ───────────────────────────────────────────────────────────

_EXTRACT_ONE_SYSTEM = """The user is asking about ONE specific block. Identify it.

Output JSON only (no markdown fence):
  {"block_name": "block_xxx" | null, "fallback_query": "<original keywords>"}

Rules:
- Canonical name uses `block_` prefix and snake_case (e.g. block_xbar_r).
- If the user wrote a partial / common name (xbar / IMR / 管制圖 / 直方圖),
  map it to the canonical name when obvious; otherwise leave block_name null
  and put descriptive keywords into fallback_query so the next step can
  search by use-case.
- Don't invent block names — when uncertain, return null.
"""


async def extract_block_target(user_message: str) -> tuple[Optional[str], str]:
    """Returns (canonical_block_name, fallback_query).

    If the user typed a `block_xxx` token verbatim we skip the LLM.
    """
    local = _local_extract_block_names(user_message)
    if local:
        return (local[0], user_message)

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_EXTRACT_ONE_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=200,
        )
        d = json.loads(_strip_code_fence(resp.text or ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.extract_block_target failed (%s) — empty", e)
        return (None, user_message)

    name = d.get("block_name")
    if name and not isinstance(name, str):
        name = None
    if name and not _BLOCK_NAME_RE.fullmatch(name):
        # Reject hallucinated shape — fall back to keyword search.
        logger.info("advisor.extract_block_target: rejected non-canonical name %r", name)
        name = None
    fallback = (d.get("fallback_query") or user_message).strip()
    return (name, fallback)


# ── COMPARE ──────────────────────────────────────────────────────────

_EXTRACT_MANY_SYSTEM = """The user is asking to compare 2-5 blocks. Identify them.

Output JSON only (no markdown fence):
  {"block_names": ["block_xxx", "block_yyy", ...], "max": 5}

Rules:
- Canonical names with `block_` prefix and snake_case.
- 2 to 5 names. If you can identify only 1, return [] — that's an EXPLAIN
  case, not COMPARE; the graph will recover.
- Don't invent names.
"""


MAX_COMPARE_BLOCKS = 5


async def extract_block_targets(user_message: str) -> list[str]:
    """Returns list of canonical block names (2..5). Empty list = couldn't
    identify enough blocks; caller should fall back to AMBIGUOUS."""
    local = _local_extract_block_names(user_message)
    if len(local) >= 2:
        return local[:MAX_COMPARE_BLOCKS]

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_EXTRACT_MANY_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=300,
        )
        d = json.loads(_strip_code_fence(resp.text or ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.extract_block_targets failed (%s) — empty", e)
        return []

    names = d.get("block_names") or []
    if not isinstance(names, list):
        return []
    valid = [n for n in names if isinstance(n, str) and _BLOCK_NAME_RE.fullmatch(n)]
    return valid[:MAX_COMPARE_BLOCKS]


# ── RECOMMEND ────────────────────────────────────────────────────────

_EXTRACT_USECASE_SYSTEM = """The user describes a use case. Distill it into
search keywords for a block registry lookup.

Output JSON only (no markdown fence):
  {"keywords": ["kw1", "kw2", ...], "intent_summary": "<one short sentence>"}

Rules:
- 2-6 keywords. Both English and Chinese terms welcome (registry has both).
- Domain terms preferred over generic verbs:
    "OOC", "outlier", "trend", "regression", "correlation", "wafer",
    "histogram", "boxplot", "control chart", "EWMA"
- intent_summary is what the user wants to ACHIEVE (1 sentence).
"""


async def extract_use_case_keywords(user_message: str) -> tuple[list[str], str]:
    """Returns (keywords, intent_summary). Used for registry search ranking."""
    client = get_llm_client()
    try:
        resp = await client.create(
            system=_EXTRACT_USECASE_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=300,
        )
        d = json.loads(_strip_code_fence(resp.text or ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.extract_use_case_keywords failed (%s) — fallback to raw", e)
        return ([user_message], user_message)

    kws = d.get("keywords") or []
    if not isinstance(kws, list):
        kws = [user_message]
    kws = [k.strip() for k in kws if isinstance(k, str) and k.strip()]
    summary = (d.get("intent_summary") or user_message).strip()
    return (kws or [user_message], summary)
