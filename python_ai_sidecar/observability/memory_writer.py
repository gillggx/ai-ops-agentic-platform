"""MemoryWriter — fast-path memory writes (V70; spec MULTI_AGENT_MEMORY_SPEC §3.2).

Fills the record-hook slots the Phase 0 skeleton reserved: deterministic graph
events (W1 plan-edit / W2 verifier-rejects / W3 repair-outcome) turn into
durable memories. Same hard rules as the EpisodeRecorder sibling:

- FAIL-OPEN: Java down never affects a build (dead-silent after first failure).
- DETERMINISTIC: what/when to write is decided by graph code + the class
  decision tree below; the LLM is not consulted (E1 — template memos in v1).
- CAPPED: per-build flood guards (E4): knowledge<=3, doc memos<=5, env-tunable.
- Server-side dedup: Java skips (user, class, title) / (block, param, episode)
  duplicates, so replays and multi-flush never double-write.

Reads come for free: new agent_knowledge rows get their embedding from the
30s backfill job, after which the EXISTING plan/execute retrieval pipeline
recalls them (spec §3.3 — zero new read-side code).
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_current_writer: contextvars.ContextVar[Optional["MemoryWriter"]] = (
    contextvars.ContextVar("memory_writer", default=None)
)

MAX_KNOWLEDGE_PER_BUILD = int(os.getenv("MEMORY_MAX_KNOWLEDGE_PER_BUILD", "3"))
MAX_DOC_MEMOS_PER_BUILD = int(os.getenv("MEMORY_MAX_DOC_MEMOS_PER_BUILD", "5"))

# ── deterministic class decision tree (spec §3.2 / AGENT_HARNESS §12) ──────
# Order matters: presentation before preference (a "改成 bar chart 最近7天"
# edit is primarily a presentation change).
_PRESENTATION_RE = re.compile(
    r"chart|圖|表格|table|bar|line|box|pareto|散佈|scatter|熱圖|heatmap|呈現|顯示|排序|sort",
    re.IGNORECASE,
)
_PREFERENCE_RE = re.compile(
    r"\d+\s*(小時|天|分鐘|筆|h\b|d\b|min)|最近|過去|範圍|時間窗|EQP-|STEP_|預設",
    re.IGNORECASE,
)


def classify_edit(from_text: str, to_text: str) -> str:
    """Deterministic memo-class for a plan edit — never LLM-chosen."""
    blob = f"{from_text} {to_text}"
    if _PRESENTATION_RE.search(blob):
        return "presentation"
    if _PREFERENCE_RE.search(blob):
        return "preference"
    return "correction"


def get_current_memory_writer() -> Optional["MemoryWriter"]:
    return _current_writer.get()


def set_current_memory_writer(w: Optional["MemoryWriter"]) -> None:
    _current_writer.set(w)


def make_memory_writer(*, episode_key: str, user_id: Optional[int]) -> Optional["MemoryWriter"]:
    """Factory — None when the flag is off (all call sites no-op)."""
    from python_ai_sidecar.feature_flags import is_memory_writes_enabled

    if not is_memory_writes_enabled():
        return None
    return MemoryWriter(episode_key=episode_key, user_id=user_id)


class MemoryWriter:
    def __init__(self, *, episode_key: str, user_id: Optional[int]):
        self.episode_key = episode_key
        # Retrieval reads with `user_id or 1` (see goal_plan) — mirror that so
        # driver/smoke builds (no auth user) still land in a recallable scope.
        self.user_id = user_id or 1
        self._knowledge_written = 0
        self._memos_written = 0
        self._dead = False

    # ── W1 / W3: agent_knowledge fast-path ─────────────────────────────
    async def write_knowledge(self, *, memo_class: str, title: str, body: str,
                              applies_to: str = "both") -> bool:
        if self._dead or self._knowledge_written >= MAX_KNOWLEDGE_PER_BUILD:
            return False
        try:
            await self._post("/internal/memory/knowledge", {
                "user_id": self.user_id,
                "memo_class": memo_class,
                "title": title[:200],
                "body": body,
                "applies_to": applies_to,
                "source": "agent_fast",
            })
            self._knowledge_written += 1
            return True
        except Exception as ex:  # noqa: BLE001 — fail-open by design
            self._dead = True
            logger.warning("MemoryWriter: knowledge write failed (%s) — disabled "
                           "for episode %s", ex, self.episode_key)
            return False

    # ── W2: Builder doc memo ────────────────────────────────────────────
    async def write_doc_memo(self, *, block_id: str, param: Optional[str],
                             memo: str, verdict_context: Optional[str]) -> bool:
        if self._dead or self._memos_written >= MAX_DOC_MEMOS_PER_BUILD:
            return False
        try:
            await self._post("/internal/memory/doc-memos", {
                "block_id": block_id,
                "param": param,
                "memo": memo,
                "verdict_context": verdict_context,
                "from_episode": self.episode_key,
            })
            self._memos_written += 1
            return True
        except Exception as ex:  # noqa: BLE001
            self._dead = True
            logger.warning("MemoryWriter: doc-memo write failed (%s) — disabled "
                           "for episode %s", ex, self.episode_key)
            return False

    async def _post(self, path: str, body: dict[str, Any]) -> None:
        import httpx

        from python_ai_sidecar.config import CONFIG

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{CONFIG.java_api_url}{path}",
                json=body,
                headers={"X-Internal-Token": CONFIG.java_internal_token},
            )
            resp.raise_for_status()
