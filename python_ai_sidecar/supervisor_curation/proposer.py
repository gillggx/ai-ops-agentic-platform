"""Supervisor curation proposer (Phase 5) — PROPOSE-ONLY, offline.

Reads the curation input from Java (draft corrections, live preference /
presentation rows, pending doc memos), asks a cheap LLM (Haiku, same cost
posture as mcp_derivative) for MERGE / CORRECT / PRUNE / PROMOTE / DOC_REVISE
proposals, deterministically validates them, and queues them via
POST /internal/supervisor/proposals.

HARD RULE (2026-07-03 pollution incident): this module NEVER mutates
agent_knowledge / block_doc_memos / block_docs. Every output is a proposal row
that a human approves in /supervisor before SupervisorCurationService commits.

Runs OFFLINE (CLI / cron), never in the build hot path — zero build-time
behaviour change by construction.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Bounded run: the reviewer is a human — don't flood the queue.
MAX_PROPOSALS_PER_RUN = 12
# Truncation caps so the Haiku call stays small and cheap.
MAX_ROWS_PER_SECTION = 30
MAX_BODY_CHARS = 400

DEFAULT_LLM_MODEL = os.environ.get(
    "SUPERVISOR_CURATION_LLM_MODEL", "claude-haiku-4-5-20251001"
)

ALLOWED_TYPES = {"MERGE", "CORRECT", "PRUNE", "PROMOTE", "DOC_REVISE"}
PROMOTE_CLASSES = {"domain", "procedure"}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


# ── validation (deterministic, unit-testable, no LLM) ────────────────────

def validate_proposal(p: dict[str, Any], known_knowledge_ids: set[int],
                      known_memo_ids: set[int]) -> Optional[str]:
    """Return an error string if the proposal is malformed, else None.

    The LLM output is untrusted: every id must exist in the curation input we
    actually sent, and every per-type required field must be present. This is
    the graph-side deterministic check (CLAUDE.md: don't trust prompt output).
    """
    t = p.get("action_type")
    if t not in ALLOWED_TYPES:
        return f"unknown action_type {t!r}"
    body = p.get("proposal")
    if not isinstance(body, dict) or not body:
        return "proposal object missing"

    def _ids(v: Any) -> list[int]:
        return [int(x) for x in v] if isinstance(v, list) else []

    if t == "MERGE":
        keep = body.get("keep_id")
        removes = _ids(body.get("remove_ids"))
        if not isinstance(keep, int) or not removes:
            return "MERGE needs keep_id + remove_ids"
        if keep in removes:
            return "MERGE keep_id must not be in remove_ids"
        unknown = [i for i in [keep, *removes] if i not in known_knowledge_ids]
        if unknown:
            return f"MERGE references unknown knowledge ids {unknown}"
    elif t == "CORRECT":
        tid = body.get("target_id")
        if not isinstance(tid, int) or not str(body.get("new_body") or "").strip():
            return "CORRECT needs target_id + new_body"
        if tid not in known_knowledge_ids:
            return f"CORRECT references unknown knowledge id {tid}"
    elif t == "PRUNE":
        ids = _ids(body.get("target_ids"))
        if not ids:
            return "PRUNE needs target_ids"
        unknown = [i for i in ids if i not in known_knowledge_ids]
        if unknown:
            return f"PRUNE references unknown knowledge ids {unknown}"
    elif t == "PROMOTE":
        if body.get("memo_class") not in PROMOTE_CLASSES:
            return "PROMOTE memo_class must be domain|procedure"
        if not str(body.get("title") or "").strip() or not str(body.get("body") or "").strip():
            return "PROMOTE needs title + body"
    elif t == "DOC_REVISE":
        ids = _ids(body.get("memo_ids"))
        if not ids or not str(body.get("block_id") or "").strip():
            return "DOC_REVISE needs block_id + memo_ids"
        unknown = [i for i in ids if i not in known_memo_ids]
        if unknown:
            return f"DOC_REVISE references unknown memo ids {unknown}"
        if not str(body.get("revised_doc_draft") or "").strip():
            return "DOC_REVISE needs revised_doc_draft"
    return None


# ── prompts (principles only — no case rules) ────────────────────────────

_SYSTEM_PROMPT = """\
你是 AIOps multi-agent 系統的 Supervisor（記憶蒸餾者）。你收到系統的記憶現況，\
產出「治理提案」。你**只提案，不執行** — 人類會逐筆審核。

五種提案（每種都要附一句 rationale）：
- MERGE：兩筆以上語意相同的 preference/presentation → 合併（keep_id 留最完整的，\
merged_body 可選）。不同語意絕不合併。
- CORRECT：draft correction（active=false 的失敗筆記）→ 改寫成乾淨、可長期使用的\
教訓（new_body 必須含 Why 與 How to apply）。只有當教訓對未來建置**明確有益且無誤導\
風險**才 promote:true。
- PRUNE：內容含糊、過時、或只描述一次性狀況、無再利用價值的 → 停用。
- PROMOTE：跨多筆記錄反覆出現的**穩定 pattern** → 蒸餾成一筆 domain（領域事實）或 \
procedure（可重用配方）。必須是從多筆證據歸納，不可從單一事件臆測。
- DOC_REVISE：同一 block 的多筆 doc memo → 寫成一段可併入 block 文件的修訂草案\
（revised_doc_draft），說明該 block 文件缺了什麼。

原則：
1. 寧缺勿濫 — 沒有把握就不提案；空清單是合法輸出。
2. 所有 id 必須來自輸入資料，禁止捏造。
3. 產出繁體中文（專有名詞可英文）。
4. 只輸出 JSON：{"proposals":[{"action_type":"...","target_ids":[...],\
"proposal":{...},"rationale":"..."}]}
"""


def _fmt_rows(rows: list[dict], keys: list[str]) -> str:
    out = []
    for r in rows[:MAX_ROWS_PER_SECTION]:
        item = {k: (str(r.get(k))[:MAX_BODY_CHARS] if r.get(k) is not None else None)
                for k in keys}
        out.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(out) if out else "(無)"


def build_user_prompt(cin: dict[str, Any]) -> str:
    kk = ["id", "title", "body", "memo_class", "written_by", "applies_to", "uses"]
    mk = ["id", "block_id", "param", "memo", "from_episode"]
    return (
        "## draft corrections（active=false，等你 CORRECT 或 PRUNE）\n"
        + _fmt_rows(cin.get("draft_corrections") or [], kk)
        + "\n\n## live preferences（找語意重複 → MERGE；過時 → PRUNE）\n"
        + _fmt_rows(cin.get("live_preferences") or [], kk)
        + "\n\n## live presentations（同上）\n"
        + _fmt_rows(cin.get("live_presentations") or [], kk)
        + "\n\n## pending doc memos（按 block 聚合 → DOC_REVISE；跨 block 穩定 pattern → PROMOTE）\n"
        + _fmt_rows(cin.get("pending_doc_memos") or [], mk)
        + "\n\n輸出提案 JSON。"
    )


# ── run ──────────────────────────────────────────────────────────────────

@dataclass
class CurationRunResult:
    proposed: int = 0
    skipped_invalid: int = 0
    deduped: int = 0
    errors: list[str] = field(default_factory=list)
    llm_model: str = DEFAULT_LLM_MODEL
    input_tokens: int = 0
    output_tokens: int = 0


def _safe_parse_json(text: str) -> Optional[dict]:
    if not text or not text.strip():
        return None
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        # last resort: outermost braces
        s, e = candidate.find("{"), candidate.rfind("}")
        if 0 <= s < e:
            try:
                parsed = json.loads(candidate[s:e + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _haiku_client():
    """Cheap pinned client — same posture as mcp_derivative (cost-controlled)."""
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
    from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings

    settings = get_settings()
    if settings.LLM_PROVIDER != "anthropic":
        logger.info("supervisor curation: LLM_PROVIDER=%s — using cached client "
                    "(model=%s) instead of Haiku.",
                    settings.LLM_PROVIDER, settings.LLM_MODEL)
        return get_llm_client()
    if not settings.ANTHROPIC_API_KEY:
        # Prod may have the Anthropic key disabled (bake-off key rotation) while
        # the builder runs via OpenRouter — honour the deployment client rather
        # than failing the whole offline pass. Haiku is a cost preference, not
        # a correctness requirement.
        logger.info("supervisor curation: no ANTHROPIC_API_KEY — falling back "
                    "to cached client.")
        return get_llm_client()
    from python_ai_sidecar.agent_helpers_native.llm_client import AnthropicLLMClient
    return AnthropicLLMClient(api_key=settings.ANTHROPIC_API_KEY,
                              model=DEFAULT_LLM_MODEL)


async def run_curation(java_base: str, internal_token: str,
                       force_client=None) -> CurationRunResult:
    """One offline curation pass: read input → LLM proposals → validate → queue."""
    import httpx

    res = CurationRunResult()
    headers = {"X-Internal-Token": internal_token}

    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.get(f"{java_base}/internal/supervisor/curation-input",
                           headers=headers)
        r.raise_for_status()
        cin = r.json().get("data") or {}

    known_k = {int(row["id"]) for sec in
               ("draft_corrections", "live_preferences", "live_presentations")
               for row in (cin.get(sec) or []) if row.get("id") is not None}
    known_m = {int(row["id"]) for row in (cin.get("pending_doc_memos") or [])
               if row.get("id") is not None}

    if not known_k and not known_m:
        logger.info("supervisor curation: nothing to curate — empty input.")
        return res

    client = force_client or _haiku_client()
    resp = await client.create(
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(cin)}],
        max_tokens=3000,
    )
    res.input_tokens = getattr(resp, "input_tokens", 0) or 0
    res.output_tokens = getattr(resp, "output_tokens", 0) or 0

    parsed = _safe_parse_json(resp.text)
    proposals = (parsed or {}).get("proposals")
    if not isinstance(proposals, list):
        res.errors.append("LLM output was not a valid proposals JSON")
        logger.warning("supervisor curation: bad LLM output: %s", resp.text[:300])
        return res

    meta = {"model": res.llm_model, "input_rows": len(known_k) + len(known_m)}
    async with httpx.AsyncClient(timeout=10.0) as http:
        for p in proposals[:MAX_PROPOSALS_PER_RUN]:
            err = validate_proposal(p if isinstance(p, dict) else {}, known_k, known_m)
            if err:
                res.skipped_invalid += 1
                logger.info("supervisor curation: skip invalid proposal (%s)", err)
                continue
            body = {
                "action_type": p["action_type"],
                "target_ids": p.get("target_ids") or [],
                "proposal": p["proposal"],
                "rationale": str(p.get("rationale") or "")[:500],
                "proposer_meta": meta,
            }
            try:
                pr = await http.post(f"{java_base}/internal/supervisor/proposals",
                                     json=body, headers=headers)
                pr.raise_for_status()
                if (pr.json().get("data") or {}).get("deduped"):
                    res.deduped += 1
                else:
                    res.proposed += 1
            except Exception as ex:  # noqa: BLE001 — keep queuing the rest
                res.errors.append(f"{p.get('action_type')}: {ex}")
                logger.warning("supervisor curation: proposal POST failed: %s", ex)
    return res
