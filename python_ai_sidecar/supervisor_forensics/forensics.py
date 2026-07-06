"""Supervisor trace forensics (W3) — offline, PROPOSE-ONLY.

Pipeline (mirrors supervisor_curation/proposer.py's offline-pass pattern):

1. Selection (zero LLM)      — read builder trace files, extract per-trace
                               failure / reject / loop signals.
2. Hotspot aggregation       — group signals by block; F3 anti-pollution
                               gate: single-case hotspots produce NOTHING.
3. Deep-dive (<= 3 LLM calls) — hard cap MAX_DEEP_DIVES; strict-JSON
                               diagnosis per hotspot.
4. Decision tree → proposals — doc_gap → DOC_REVISE, planning_knowledge
                               (>=3 distinct requests) → PROMOTE,
                               code_suspect → ISSUE, inconclusive → nothing.
5. CFG detection (zero LLM)  — provider empty-response rate from Java's
                               llm-usage daily rollup.
6. Verify pass (zero LLM)    — recompute before/after reject counts for
                               landed proposals in the verify queue.

HARD RULES:
- Anti-memory-pollution: hotspots seen in only ONE distinct request are
  dropped entirely (logged, no proposal). Knowledge (PROMOTE) additionally
  requires >= KNOWLEDGE_MIN_DISTINCT distinct requests.
- PROPOSE-ONLY: every output is a proposal row a human approves in
  /supervisor. This module never writes agent_knowledge / block docs.
- Runs OFFLINE (CLI / cron) — zero build-time behaviour change.

Defensive against not-yet-landed Java W3 endpoints: proposals-open,
llm-usage/daily, verify-queue and the per-proposal verify POST may all 404 —
each is skipped gracefully with a log, never an exception.

Activity-id dedupe vs supersede (complementary, both keyed on the subject
block): every posted proposal carries proposer_meta.activity_ids — the full
trace basenames backing the hotspot (CFG: "llm-daily:<date>:<model>").
Same subject + >= 1 overlapping activity id with an open proposal = SAME
evidence → skip (deduped). Same subject + disjoint ids = NEW evidence →
supersede the open proposal, as before.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Reuse the curation pass's LLM client selection + tolerant JSON parsing —
# same cost posture (Haiku pin with deployment-client fallback).
from python_ai_sidecar.supervisor_curation.proposer import (  # noqa: F401
    _haiku_client,
    _safe_parse_json,
)

logger = logging.getLogger(__name__)

# ── constants (no magic numbers inline) ──────────────────────────────────

#: Hard cap on LLM calls per run — forensics is a cheap offline pass.
MAX_DEEP_DIVES = 3
#: F3 anti-pollution gate: hotspot needs >= 2 DISTINCT request strings.
MIN_DISTINCT_REQUESTS = 2
#: Knowledge (PROMOTE) generalization gate: >= 3 distinct requests.
KNOWLEDGE_MIN_DISTINCT = 3
#: Within one trace, this many inspect_block_doc on the same block = loop signal.
LOOP_INSPECT_THRESHOLD = 3
#: Within one trace, this many verifier rejects on the same block = loop signal.
LOOP_REJECT_THRESHOLD = 3
#: Per-trace compact summary budget in the deep-dive prompt.
TRACE_SUMMARY_CHAR_BUDGET = 6000
#: How many trace summaries per deep-dive prompt.
MAX_SUMMARIES_PER_DIVE = 2
#: Current block doc budget in the deep-dive prompt.
BLOCK_DOC_CHAR_BUDGET = 4000
#: CFG: only consider models with at least this many calls today.
CFG_MIN_CALLS = 50
#: CFG: empty-response rate strictly above this triggers a proposal.
CFG_EMPTY_RATE_THRESHOLD = 0.20
#: Default trace selection window.
DEFAULT_DAYS = 7
#: Verify pass compares reject counts over this window on each side.
VERIFY_WINDOW_DAYS = 7

DEFAULT_STATE_FILE = "/tmp/supervisor-forensics-state.json"
DEFAULT_TRACE_DIR = "/tmp/builder-traces"

#: Trace-level statuses that mean "this build failed-ish".
FAILED_STATUSES = {"handover_pending", "failed"}
#: graph_steps statuses that mean "this build failed-ish" regardless of status.
FAILED_STEP_STATUSES = {"empty_response_escalated", "round_max_hit"}

ROOT_CAUSE_LAYERS = {"doc_gap", "planning_knowledge", "code_suspect", "inconclusive"}
KNOWLEDGE_CLASSES = {"domain", "procedure"}
KNOWLEDGE_APPLIES = {"plan", "execute", "both"}

_NARRATIVE_CAP = 300


# ═════════════════════════════════════════════════════════════════════════
# Stage 1 — selection (zero LLM, pure trace parsing)
# ═════════════════════════════════════════════════════════════════════════

@dataclass
class TraceSignals:
    """Deterministic signals extracted from one builder trace file."""
    path: str
    build_id: Optional[str]
    instruction: str
    status: str
    failed_ish: bool
    round_max_hits: int
    empty_response_escalated: bool
    rounds_used: int
    rejects_by_block: dict[str, int]
    inspects_by_block: dict[str, int]
    blocks_touched: list[str]
    started_at: Optional[str]
    mtime: float
    # sidecar session_id == agent-activity episode_key（調閱鏈的 join key）；
    # 放最後帶預設值 — 既有測試以位置參數建構。
    session_id: Optional[str] = None

    @property
    def ref(self) -> str:
        """Human-usable trace reference (file basename)."""
        return os.path.basename(self.path)


def extract_signals(trace: dict, path: str, mtime: float = 0.0) -> TraceSignals:
    """Extract the forensics signals from one trace dict.

    Signals (all deterministic):
    - failed_ish: status in FAILED_STATUSES OR any graph_step with status in
      {empty_response_escalated, round_max_hit}.
    - rejects_by_block: verifier no_match count per candidate block. Primary
      source is verifier_decisions (verdict='no_match'); legacy traces
      without verifier_decisions fall back to graph_steps phase_verifier
      no_match entries (block_id). Never both — avoids double counting,
      since each phase_verifier no_match step mirrors one verifier_decision.
    - inspects_by_block: repeated inspect_block_doc per block, read from
      decision_records tool_use args (fallback: llm_calls parsed args).
    - blocks_touched: block_name / block_id args seen in decision_records
      (add_node / commit_pick / inspect...) + decision_metadata.actual_pick.
    """
    steps = trace.get("graph_steps") or []
    status = str(trace.get("status") or "")

    round_max_hits = sum(
        1 for s in steps
        if isinstance(s, dict) and s.get("status") == "round_max_hit"
    )
    escalated = any(
        isinstance(s, dict) and s.get("status") == "empty_response_escalated"
        for s in steps
    )
    failed_ish = status in FAILED_STATUSES or escalated or round_max_hits > 0

    rounds_used = sum(
        1 for s in steps
        if isinstance(s, dict)
        and s.get("node") == "agentic_phase_loop"
        and s.get("status") == "round_done"
    )

    # Rejects — primary: verifier_decisions; fallback: phase_verifier steps.
    rejects: Counter[str] = Counter()
    verifier_decisions = trace.get("verifier_decisions") or []
    if verifier_decisions:
        for d in verifier_decisions:
            if not isinstance(d, dict) or d.get("verdict") != "no_match":
                continue
            block = str(d.get("candidate_block") or "").strip()
            if block:
                rejects[block] += 1
    else:
        for s in steps:
            if not isinstance(s, dict):
                continue
            if s.get("node") == "phase_verifier" and s.get("status") == "no_match":
                block = str(s.get("block_id") or "").strip()
                if block:
                    rejects[block] += 1

    # Inspect counts + blocks touched — from decision_records tool args.
    inspects: Counter[str] = Counter()
    touched: list[str] = []

    def _note_touch(block: Any) -> None:
        b = str(block or "").strip()
        if b and b not in touched:
            touched.append(b)

    records = trace.get("decision_records") or []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        tool_use = ((rec.get("llm_response") or {}).get("tool_use")) or {}
        if isinstance(tool_use, dict):
            args = tool_use.get("input") or tool_use.get("args") or {}
            block = None
            if isinstance(args, dict):
                block = args.get("block_id") or args.get("block_name")
            if block:
                _note_touch(block)
                if tool_use.get("name") == "inspect_block_doc":
                    inspects[str(block).strip()] += 1
        meta = rec.get("decision_metadata") or {}
        if isinstance(meta, dict) and meta.get("actual_pick"):
            _note_touch(meta["actual_pick"])

    if not records:
        # Legacy traces: decision_records absent — fall back to llm_calls.
        for c in trace.get("llm_calls") or []:
            if not isinstance(c, dict):
                continue
            parsed = c.get("parsed") or {}
            if not isinstance(parsed, dict):
                continue
            args = parsed.get("args") or parsed.get("input") or {}
            block = args.get("block_id") or args.get("block_name") \
                if isinstance(args, dict) else None
            if block:
                _note_touch(block)
                if parsed.get("name") == "inspect_block_doc":
                    inspects[str(block).strip()] += 1

    return TraceSignals(
        path=path,
        build_id=trace.get("build_id"),
        session_id=(str(trace.get("session_id")) if trace.get("session_id") else None),
        instruction=str(trace.get("instruction") or "").strip(),
        status=status,
        failed_ish=failed_ish,
        round_max_hits=round_max_hits,
        empty_response_escalated=escalated,
        rounds_used=rounds_used,
        rejects_by_block=dict(rejects),
        inspects_by_block=dict(inspects),
        blocks_touched=touched,
        started_at=trace.get("started_at"),
        mtime=mtime,
    )


def load_traces(trace_dir: Path | str, *, days: Optional[int] = DEFAULT_DAYS,
                now: Optional[datetime] = None) -> list[TraceSignals]:
    """Read *.json traces under trace_dir with mtime within the last `days`.

    days=None disables the mtime filter (used by the verify pass which
    needs the before-landing window too). Unreadable / non-trace files are
    skipped with a log — one corrupt file must not kill the run.
    """
    d = Path(trace_dir)
    if not d.is_dir():
        logger.info("forensics: trace dir %s missing — nothing to scan", d)
        return []
    now = now or datetime.now(tz=timezone.utc)
    cutoff = now.timestamp() - days * 86400 if days is not None else None
    out: list[TraceSignals] = []
    for p in sorted(d.glob("*.json")):
        try:
            mtime = p.stat().st_mtime
        except OSError as ex:
            logger.warning("forensics: stat %s failed: %s", p, ex)
            continue
        if cutoff is not None and mtime < cutoff:
            continue
        try:
            trace = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as ex:
            logger.warning("forensics: skip unreadable trace %s: %s", p, ex)
            continue
        if not isinstance(trace, dict):
            logger.warning("forensics: skip non-object trace %s", p)
            continue
        out.append(extract_signals(trace, str(p), mtime))
    return out


# ═════════════════════════════════════════════════════════════════════════
# Stage 2 — hotspot aggregation + F3 anti-pollution gate (zero LLM)
# ═════════════════════════════════════════════════════════════════════════

@dataclass
class Hotspot:
    """All signals for one block across the selected traces."""
    block: str
    signals: list[TraceSignals] = field(default_factory=list)

    @property
    def distinct_requests(self) -> list[str]:
        seen: list[str] = []
        for s in self.signals:
            key = s.instruction.strip()
            if key and key not in seen:
                seen.append(key)
        return seen

    @property
    def distinct_request_count(self) -> int:
        return len(self.distinct_requests)

    @property
    def reject_count(self) -> int:
        return sum(s.rejects_by_block.get(self.block, 0) for s in self.signals)

    @property
    def loop_signals(self) -> int:
        n = 0
        for s in self.signals:
            if s.inspects_by_block.get(self.block, 0) >= LOOP_INSPECT_THRESHOLD:
                n += 1
            if s.rejects_by_block.get(self.block, 0) >= LOOP_REJECT_THRESHOLD:
                n += 1
        return n

    @property
    def failed_trace_count(self) -> int:
        return sum(1 for s in self.signals if s.failed_ish)

    @property
    def trace_refs(self) -> list[str]:
        return [s.ref for s in self.signals]

    @property
    def activity_ids(self) -> list[str]:
        """Agent-activity episode keys（= trace session_id）；legacy trace
        沒有 session_id 時退回 trace basename。去重保序。"""
        out: list[str] = []
        for s in self.signals:
            aid = s.session_id or s.ref
            if aid not in out:
                out.append(aid)
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "distinct_request_count": self.distinct_request_count,
            "reject_count": self.reject_count,
            "loop_signals": self.loop_signals,
            "failed_trace_count": self.failed_trace_count,
            "traces": self.trace_refs,
        }


def _block_has_signal(s: TraceSignals, block: str) -> bool:
    """A trace contributes a block to a hotspot only on a real friction
    signal — a verifier reject or a repeated-inspect loop. Merely touching
    a block in a failed build is NOT evidence against that block."""
    return (
        s.rejects_by_block.get(block, 0) > 0
        or s.inspects_by_block.get(block, 0) >= LOOP_INSPECT_THRESHOLD
    )


def aggregate_hotspots(
    signals: list[TraceSignals],
) -> tuple[list[Hotspot], list[dict[str, Any]]]:
    """Group signals by block → ranked hotspots + dropped (F3-gated) list.

    Rank: (distinct_request_count desc, reject_count desc, block asc).
    F3 gate: distinct_request_count < MIN_DISTINCT_REQUESTS → dropped
    entirely (returned separately so callers can log what was suppressed).
    """
    by_block: dict[str, Hotspot] = {}
    for s in signals:
        candidate_blocks = set(s.rejects_by_block) | {
            b for b, n in s.inspects_by_block.items()
            if n >= LOOP_INSPECT_THRESHOLD
        }
        for block in candidate_blocks:
            if not _block_has_signal(s, block):
                continue
            by_block.setdefault(block, Hotspot(block=block)).signals.append(s)

    ranked = sorted(
        by_block.values(),
        key=lambda h: (-h.distinct_request_count, -h.reject_count, h.block),
    )
    kept: list[Hotspot] = []
    dropped: list[dict[str, Any]] = []
    for h in ranked:
        if h.distinct_request_count < MIN_DISTINCT_REQUESTS:
            dropped.append(h.stats())
            logger.info(
                "forensics F3 gate: drop single-case hotspot block=%s "
                "(distinct_requests=%d rejects=%d traces=%s) — 單一案例不產出",
                h.block, h.distinct_request_count, h.reject_count, h.trace_refs,
            )
            continue
        kept.append(h)
    return kept, dropped


# ═════════════════════════════════════════════════════════════════════════
# Stage 3 — deep-dive (<= MAX_DEEP_DIVES LLM calls, strict JSON out)
# ═════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
你是 AIOps 建置系統的 Supervisor（trace 鑑識員）。你收到一個「hotspot」：\
多個 user request 在同一個 block 上反覆被驗證拒絕或陷入迴圈。你的任務是判斷\
根因屬於哪一層，並草擬可供人審核的修正草案。你**只診斷與草擬，不執行**。

根因分層（擇一）：
- doc_gap：block 文件（description / param_schema / examples）缺漏或誤導，\
導致 agent 誤選或誤用。→ 必附 doc_revision_draft（一段可直接併入 block 文件\
的修訂草案，寫原則與語意，不列 case 清單）。
- planning_knowledge：跨 request 的穩定規劃教訓，單一 block 文件救不了\
（例如「先列機台再 foreach」這類配方）。→ 必附 knowledge_draft 與 \
generalization（一句可泛化的原則）。
- code_suspect：文件正確但 block 執行端／驗證端行為不符 — 疑似程式問題。
- inconclusive：證據不足，無法判斷。

原則：
1. 寧缺勿濫 — 證據不足就回 inconclusive，不要臆測。
2. diagnosis 必須引用輸入內的具體訊號（拒絕原因、round 數、inspect 次數），\
禁止捏造輸入沒有的事實。
3. 草案寫原則，不寫個案規則。
4. 繁體中文（專有名詞可英文）。

輸出「嚴格 JSON」（欄位名錯一個字整份輸出會被系統丟棄）：
{"root_cause_layer": "doc_gap"|"planning_knowledge"|"code_suspect"|"inconclusive",
 "diagnosis": "一段診斷（引用具體訊號）",
 "doc_revision_draft": "..."|null,
 "knowledge_draft": {"title": "...", "body": "...", "memo_class": "domain"|"procedure", "applies_to": "plan"|"execute"|"both"}|null,
 "headline": "≤20 字的人話重點（給簽核者掃讀用，例：sigma_source 文件缺口）",
 "generalization": "..."|null}
"""


def compact_trace_summary(trace: dict, *, budget: int = TRACE_SUMMARY_CHAR_BUDGET) -> str:
    """Aggressively-truncated summary of one trace for the deep-dive prompt.

    Built on trace_summary.parse (the canonical trace → phase/attempt model)
    then pruned: keep instruction / plan / per-phase outcome + attempt
    verdicts, drop raw args and catalogs. Hard char cap at `budget`.
    """
    try:
        from python_ai_sidecar.agent_builder.graph_build import trace_summary
        model = trace_summary.parse(trace)
    except Exception as ex:  # noqa: BLE001 — a weird trace must not kill the pass
        logger.warning("forensics: trace_summary.parse failed: %s", ex)
        model = {
            "instruction": trace.get("instruction"),
            "plan": [],
            "phases": [],
            "end": {"status": trace.get("status")},
        }

    def _compact_attempt(a: dict) -> dict:
        out: dict[str, Any] = {}
        if a.get("kind") == "revise":
            out["kind"] = "revise"
            out["root_cause"] = a.get("root_cause")
            return out
        out["block"] = a.get("block_id")
        if a.get("inspect_count"):
            out["inspects"] = a["inspect_count"]
        v = a.get("verify")
        if isinstance(v, dict):
            out["verify"] = {
                k: v.get(k)
                for k in ("verdict", "result", "error_message",
                          "judge_reject_reason", "would_pass")
                if v.get(k)
            }
        return out

    compact = {
        "instruction": model.get("instruction"),
        "status": trace.get("status"),
        "plan": model.get("plan"),
        "phases": [
            {
                "id": p.get("id"),
                "expected": p.get("expected"),
                "outcome": p.get("outcome"),
                "rounds_used": p.get("rounds_used"),
                "attempts": [_compact_attempt(a) for a in (p.get("attempts") or [])],
            }
            for p in (model.get("phases") or [])
        ],
        "final_nodes": [
            n.get("block_id") for n in ((model.get("end") or {}).get("nodes") or [])
        ],
    }
    text = json.dumps(compact, ensure_ascii=False, default=str)
    if len(text) > budget:
        text = text[:budget] + "…[truncated]"
    return text


def build_deepdive_prompt(hotspot: Hotspot, summaries: list[str],
                          block_doc: str) -> str:
    stats = json.dumps(hotspot.stats(), ensure_ascii=False)
    reqs = "\n".join(f"- {r[:200]}" for r in hotspot.distinct_requests[:8])
    parts = [
        f"## Hotspot 統計\n{stats}",
        f"## Distinct requests\n{reqs or '(無)'}",
        f"## Block「{hotspot.block}」目前文件\n{block_doc[:BLOCK_DOC_CHAR_BUDGET] or '(no doc found)'}",
    ]
    for i, s in enumerate(summaries[:MAX_SUMMARIES_PER_DIVE], 1):
        parts.append(f"## Trace summary {i}\n{s}")
    parts.append("依系統指示輸出嚴格 JSON 診斷。")
    return "\n\n".join(parts)


def validate_diagnosis(d: Any) -> Optional[str]:
    """Deterministic gate on the untrusted LLM diagnosis. Returns error or None."""
    if not isinstance(d, dict):
        return "diagnosis is not a JSON object"
    layer = d.get("root_cause_layer")
    if layer not in ROOT_CAUSE_LAYERS:
        return f"unknown root_cause_layer {layer!r}"
    if not str(d.get("diagnosis") or "").strip():
        return "diagnosis text missing"
    if layer == "doc_gap":
        if not str(d.get("doc_revision_draft") or "").strip():
            return "doc_gap needs doc_revision_draft"
    if layer == "planning_knowledge":
        kd = d.get("knowledge_draft")
        if not isinstance(kd, dict):
            return "planning_knowledge needs knowledge_draft"
        if not str(kd.get("title") or "").strip() or not str(kd.get("body") or "").strip():
            return "knowledge_draft needs title + body"
        if kd.get("memo_class") not in KNOWLEDGE_CLASSES:
            return "knowledge_draft memo_class must be domain|procedure"
        if kd.get("applies_to") not in KNOWLEDGE_APPLIES:
            return "knowledge_draft applies_to must be plan|execute|both"
        if not str(d.get("generalization") or "").strip():
            return "planning_knowledge needs generalization"
    return None


# ═════════════════════════════════════════════════════════════════════════
# Stage 4 — decision tree → proposal + narrative (deterministic)
# ═════════════════════════════════════════════════════════════════════════

def decide_action(hotspot: Hotspot, diagnosis: dict) -> Optional[dict[str, Any]]:
    """Map a validated diagnosis to a proposal, or None (with a log).

    Returns {"action_type", "proposal", "rationale"} — narrative is composed
    separately. Gates:
    - planning_knowledge with < KNOWLEDGE_MIN_DISTINCT distinct requests →
      None（泛化門檻未過，不產出）.
    - inconclusive → None.
    """
    layer = diagnosis.get("root_cause_layer")
    diag_text = str(diagnosis.get("diagnosis") or "").strip()
    trace_refs = hotspot.trace_refs

    headline = str(diagnosis.get("headline") or "").strip()[:20]

    if layer == "doc_gap":
        return {
            "action_type": "DOC_REVISE",
            "proposal": {
                "block_id": hotspot.block,
                "display_title": f"[{hotspot.block}] 文件修訂 — {headline or '用法說明缺口'}"[:48],
                "revised_doc_draft": str(diagnosis.get("doc_revision_draft") or ""),
                "trace_refs": trace_refs,
            },
            "rationale": diag_text,
        }
    if layer == "planning_knowledge":
        if hotspot.distinct_request_count < KNOWLEDGE_MIN_DISTINCT:
            logger.info(
                "forensics: block=%s 泛化門檻未過，不產出 knowledge "
                "(distinct_requests=%d < %d)",
                hotspot.block, hotspot.distinct_request_count,
                KNOWLEDGE_MIN_DISTINCT,
            )
            return None
        kd = diagnosis.get("knowledge_draft") or {}
        return {
            "action_type": "PROMOTE",
            "proposal": {
                # display_title = 掃讀用短標題（UI）；title = 入庫的知識標題
                # （Java PROMOTE commit 讀它，不可縮短）
                "display_title": (f"[{hotspot.block}] 蒸餾知識"
                                  f"（{hotspot.distinct_request_count} requests）"
                                  f" — {headline or '規劃層原則'}")[:48],
                "title": str(kd.get("title") or ""),
                "body": str(kd.get("body") or ""),
                "memo_class": str(kd.get("memo_class") or ""),
                "applies_to": str(kd.get("applies_to") or ""),
                "generalization": str(diagnosis.get("generalization") or ""),
                "trace_refs": trace_refs,
            },
            "rationale": diag_text,
        }
    if layer == "code_suspect":
        return {
            "action_type": "ISSUE",
            "proposal": {
                "display_title": f"[{hotspot.block}] 疑似誤殺 — {headline or 'verifier/graph 行為'}"[:48],
                "summary": diag_text,
                "trace_refs": trace_refs,
                "suspect": f"block {hotspot.block} 執行端/驗證端行為與文件不符",
            },
            "rationale": diag_text,
        }
    # inconclusive (validate_diagnosis gates unknown layers before this)
    logger.info("forensics: block=%s diagnosis inconclusive — 不產出", hotspot.block)
    return None


def _happened_line(hotspot: Hotspot) -> str:
    total_signals = hotspot.reject_count + hotspot.loop_signals
    return (
        f"{hotspot.distinct_request_count} 個 request 在 {hotspot.block} "
        f"累積 {total_signals} 次拒/迴圈訊號（trace ×{len(hotspot.signals)}）"
    )


def compose_forensics_narrative(hotspot: Hotspot, diagnosis: dict,
                                action_type: str) -> dict[str, Any]:
    """四段敘事 {happened, observed, subject, action} — deterministic."""
    happened = _happened_line(hotspot)
    if action_type == "PROMOTE":
        gen = str(diagnosis.get("generalization") or "").strip()
        if gen:
            happened = f"{happened}；泛化：{gen}"
        kd = diagnosis.get("knowledge_draft") or {}
        action = (
            f"蒸餾為 1 筆 {kd.get('memo_class')} 知識：「{str(kd.get('title') or '')[:80]}」"
            f"（{hotspot.distinct_request_count} 個 distinct request 佐證，人審核後生效）"
        )
    elif action_type == "DOC_REVISE":
        action = f"以修訂草案更新 {hotspot.block} 的 block 文件（人審核後生效）"
    elif action_type == "ISSUE":
        action = f"開 issue 追查 {hotspot.block} 的執行端/驗證端行為（人確認後處理）"
    else:  # defensive — decide_action only emits the three types above
        action = action_type
    return {
        "happened": happened[:_NARRATIVE_CAP],
        "observed": str(diagnosis.get("diagnosis") or "")[:_NARRATIVE_CAP],
        "subject": {"kind": "block", "id": hotspot.block,
                    "label": hotspot.block[:150]},
        "action": action[:_NARRATIVE_CAP],
    }


# ═════════════════════════════════════════════════════════════════════════
# Stage 5 — CFG detection (zero LLM) + state-file dedupe
# ═════════════════════════════════════════════════════════════════════════

def _as_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def normalize_daily_rows(data: Any) -> list[dict]:
    """The llm-usage daily endpoint hasn't landed — accept a bare list or a
    dict wrapping the list under a few plausible keys."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("rows", "models", "daily", "data"):
            v = data.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def cfg_findings(rows: list[dict], *, min_calls: int = CFG_MIN_CALLS,
                 threshold: float = CFG_EMPTY_RATE_THRESHOLD) -> list[dict]:
    """Models with calls >= min_calls AND empty rate strictly > threshold."""
    out: list[dict] = []
    for r in rows:
        model = str(r.get("model") or "").strip()
        calls = _as_int(r.get("calls"))
        empty = _as_int(r.get("empty_calls") if r.get("empty_calls") is not None
                        else r.get("empty"))
        if not model or calls < min_calls:
            continue
        rate = empty / calls
        if rate > threshold:
            out.append({
                "model": model,
                "calls": calls,
                "empty_calls": empty,
                "empty_rate": round(rate, 4),
            })
    return out


def compose_cfg_narrative(f: dict) -> dict[str, Any]:
    pct = round(f["empty_rate"] * 100, 1)
    return {
        "happened": (
            f"{f['model']} 今日空回應率 {pct}%（{f['empty_calls']}/{f['calls']}）"
        )[:_NARRATIVE_CAP],
        "observed": "provider 品質異常，重試放大成本",
        "subject": {"kind": "general", "id": f["model"], "label": f["model"][:150]},
        "action": "建議暫改 provider pin / 調整重試上限（人執行）",
    }


def load_state(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save_state(path: str, state: dict[str, Any]) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(state, ensure_ascii=False),
                              encoding="utf-8")
    except OSError as ex:
        logger.warning("forensics: cannot write state file %s: %s", path, ex)


def cfg_already_posted(state: dict, day: str, model: str) -> bool:
    posted = state.get("cfg_posted")
    return isinstance(posted, dict) and model in (posted.get(day) or [])


def mark_cfg_posted(state: dict, day: str, model: str) -> None:
    posted = state.setdefault("cfg_posted", {})
    if not isinstance(posted, dict):
        posted = state["cfg_posted"] = {}
    # keep only today — history has no dedupe value and would grow unbounded
    for key in [k for k in posted if k != day]:
        del posted[key]
    models = posted.setdefault(day, [])
    if model not in models:
        models.append(model)


# ═════════════════════════════════════════════════════════════════════════
# Stage 6 — verify pass (zero LLM)
# ═════════════════════════════════════════════════════════════════════════

def _signal_dt(s: TraceSignals) -> Optional[datetime]:
    if s.started_at:
        try:
            dt = datetime.fromisoformat(str(s.started_at).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if s.mtime:
        return datetime.fromtimestamp(s.mtime, tz=timezone.utc)
    return None


def rejects_in_window(signals: list[TraceSignals], block: str,
                      start: datetime, end: datetime) -> tuple[int, int]:
    """(reject_count, traces_touching_block) for `block` within [start, end)."""
    rejects = 0
    touched = 0
    for s in signals:
        dt = _signal_dt(s)
        if dt is None or not (start <= dt < end):
            continue
        r = s.rejects_by_block.get(block, 0)
        if r or block in s.inspects_by_block or block in s.blocks_touched:
            touched += 1
        rejects += r
    return rejects, touched


def compose_doc_verify_result(block: str, signals: list[TraceSignals],
                              landed_at: datetime) -> str:
    window = timedelta(days=VERIFY_WINDOW_DAYS)
    before, touched_b = rejects_in_window(signals, block, landed_at - window, landed_at)
    after, touched_a = rejects_in_window(signals, block, landed_at, landed_at + window)
    if touched_b == 0 and touched_a == 0:
        return "insufficient data"
    return f"拒因 {block} {before}→{after}（{VERIFY_WINDOW_DAYS}d 窗）"


def compose_cfg_verify_result(model: str, before_rate: float,
                              daily_rows: list[dict]) -> str:
    cur = next((r for r in daily_rows if str(r.get("model")) == model), None)
    calls = _as_int(cur.get("calls")) if cur else 0
    if not cur or calls <= 0:
        return "insufficient data"
    empty = _as_int(cur.get("empty_calls") if cur.get("empty_calls") is not None
                    else cur.get("empty"))
    after_rate = empty / calls
    return f"{model} 空回應率 {before_rate * 100:.1f}%→{after_rate * 100:.1f}%（daily）"


# ═════════════════════════════════════════════════════════════════════════
# HTTP helpers — same X-Internal-Token posture as supervisor_curation.
# Every GET is defensive: the Java W3 endpoints (proposals-open,
# llm-usage/daily, verify-queue, proposals/{id}/verify) may not exist yet.
# ═════════════════════════════════════════════════════════════════════════

async def _get(http: Any, url: str, headers: dict,
               params: Optional[dict] = None) -> tuple[int, Any]:
    """GET → (status_code, data-or-None). Never raises; 404 is a soft skip."""
    try:
        r = await http.get(url, headers=headers, params=params)
    except Exception as ex:  # noqa: BLE001 — network failure = graceful skip
        logger.warning("forensics: GET %s failed: %s", url, ex)
        return 0, None
    code = getattr(r, "status_code", 0)
    if code != 200:
        return code, None
    try:
        body = r.json()
    except ValueError:
        return code, None
    if isinstance(body, dict) and "data" in body:
        return code, body.get("data")
    return code, body


async def _post(http: Any, url: str, headers: dict, body: dict) -> tuple[int, Any]:
    try:
        r = await http.post(url, json=body, headers=headers)
    except Exception as ex:  # noqa: BLE001
        logger.warning("forensics: POST %s failed: %s", url, ex)
        return 0, None
    code = getattr(r, "status_code", 0)
    try:
        payload = r.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and "data" in payload:
        payload = payload.get("data")
    return code, payload


async def _fetch_block_doc(http: Any, java_base: str, headers: dict,
                           block_id: str) -> str:
    """Current block doc: /internal/block-docs first (markdown), fall back
    to the /internal/blocks catalog description + param_schema."""
    code, data = await _get(
        http, f"{java_base}/internal/block-docs/{block_id}/1.0.0", headers)
    if code == 200 and isinstance(data, dict):
        md = str(data.get("markdown") or "")
        if md.strip():
            return md[:BLOCK_DOC_CHAR_BUDGET]
    code, rows = await _get(http, f"{java_base}/internal/blocks", headers)
    if code == 200 and isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and r.get("name") == block_id:
                desc = str(r.get("description") or "")
                schema = r.get("param_schema") or r.get("paramSchema") or ""
                return (f"{desc}\n\nparam_schema:\n{schema}")[:BLOCK_DOC_CHAR_BUDGET]
    logger.info("forensics: no doc found for block %s (HTTP %s)", block_id, code)
    return "(no doc found)"


async def _fetch_open_proposals(http: Any, java_base: str,
                                headers: dict) -> Optional[list[dict]]:
    """GET /internal/supervisor/proposals-open. The Java W3 workstream may
    not have landed this yet — 404 (or any failure) skips supersede
    detection gracefully."""
    code, data = await _get(
        http, f"{java_base}/internal/supervisor/proposals-open", headers)
    if code != 200 or not isinstance(data, list):
        logger.info(
            "forensics: proposals-open unavailable (HTTP %s) — "
            "skip supersede detection", code)
        return None
    return [r for r in data if isinstance(r, dict)]


def resolve_supersede(action_type: str, subject_id: str,
                      supersede_map: Optional[dict],
                      open_proposals: Optional[list[dict]]) -> Optional[int]:
    """Old proposal id this one supersedes. Priority: --supersede-map
    ("ACTION:subject" key wins over bare "subject"), then the open-proposal
    list (match on action_type + subject block/model)."""
    if supersede_map:
        v = supersede_map.get(f"{action_type}:{subject_id}")
        if v is None:
            v = supersede_map.get(subject_id)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                logger.warning("forensics: bad supersede-map value %r for %s",
                               v, subject_id)
    for row in open_proposals or []:
        if str(row.get("action_type") or "") != action_type:
            continue
        prop = row.get("proposal")
        if isinstance(prop, str):
            try:
                prop = json.loads(prop)
            except json.JSONDecodeError:
                prop = {}
        subj = None
        if isinstance(prop, dict):
            subj = prop.get("block_id") or prop.get("model")
        if subj is None:
            nar = row.get("narrative")
            if isinstance(nar, str):
                try:
                    nar = json.loads(nar)
                except json.JSONDecodeError:
                    nar = {}
            if isinstance(nar, dict):
                subj = (nar.get("subject") or {}).get("id")
        if subj == subject_id and row.get("id") is not None:
            try:
                return int(row["id"])
            except (TypeError, ValueError):
                return None
    return None


# ── activity-id dedupe (skip when the OPEN proposal already covers the
#    exact same evidence; supersede stays for NEW evidence) ────────────────

def _parse_json_field(v: Any) -> Any:
    """Java rows may carry jsonb columns as dicts or as JSON strings —
    normalise defensively; unparseable → None (never raises)."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None
    return v


def open_proposal_subject(row: dict) -> Optional[str]:
    """Subject block/model of an open proposal, parsed defensively:
    proposal.block_id / proposal.model → narrative.subject.id →
    proposer_meta.block. Returns None when nothing identifiable."""
    prop = _parse_json_field(row.get("proposal"))
    if isinstance(prop, dict):
        subj = prop.get("block_id") or prop.get("model")
        if subj:
            return str(subj)
    nar = _parse_json_field(row.get("narrative"))
    if isinstance(nar, dict):
        subj = (nar.get("subject") or {}).get("id")
        if subj:
            return str(subj)
    meta = _parse_json_field(row.get("proposer_meta"))
    if isinstance(meta, dict) and meta.get("block"):
        return str(meta["block"])
    return None


def open_proposal_activity_ids(row: dict) -> list[str]:
    """proposer_meta.activity_ids of an open proposal (empty for proposals
    posted before activity ids existed — those never dedupe, only supersede)."""
    meta = _parse_json_field(row.get("proposer_meta"))
    if isinstance(meta, dict):
        ids = meta.get("activity_ids")
        if isinstance(ids, list):
            return [str(x) for x in ids if str(x or "").strip()]
    return []


def find_activity_dedupe(subject_id: str, activity_ids: list[str],
                         open_proposals: Optional[list[dict]]) -> Optional[Any]:
    """Open-proposal id whose subject matches AND whose activity_ids share
    >= 1 id with the new evidence — i.e. the queue already holds a proposal
    for the SAME evidence → caller skips posting (deduped). Disjoint ids or
    no recorded ids → None, and the supersede path handles it (NEW evidence
    replaces the stale open proposal)."""
    new_ids = set(activity_ids)
    if not new_ids:
        return None
    for row in open_proposals or []:
        if not isinstance(row, dict):
            continue
        if open_proposal_subject(row) != str(subject_id):
            continue
        if new_ids & set(open_proposal_activity_ids(row)):
            return row.get("id")
    return None


# ═════════════════════════════════════════════════════════════════════════
# Run orchestration
# ═════════════════════════════════════════════════════════════════════════

@dataclass
class ForensicsRunResult:
    traces_scanned: int = 0
    failed_traces: int = 0
    hotspots: int = 0
    dropped_single_case: int = 0
    deep_dives: int = 0
    proposed: int = 0
    deduped: int = 0
    skipped_invalid: int = 0
    skipped_gated: int = 0
    cfg_proposed: int = 0
    cfg_deduped: int = 0
    verified: int = 0
    errors: list[str] = field(default_factory=list)
    llm_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _proposal_body(action_type: str, proposal: dict, narrative: dict,
                   rationale: str, meta: dict,
                   supersedes: Optional[int]) -> dict[str, Any]:
    """Wire body for POST /internal/supervisor/proposals — same shape as
    supervisor_curation (proposal / narrative json.dumps'd for the jsonb
    columns). `supersedes` is an optional extra key the Java W3 workstream
    will read; unknown keys are ignored by today's controller."""
    body = {
        "action_type": action_type,
        "target_ids": [],
        "proposal": json.dumps(proposal, ensure_ascii=False),
        "narrative": json.dumps(narrative, ensure_ascii=False),
        "rationale": str(rationale or "")[:500],
        "proposer_meta": meta,
    }
    if supersedes is not None:
        body["supersedes"] = supersedes
    return body


async def _dispatch_proposal(http: Any, java_base: str, headers: dict,
                             body: dict, *, dry_run: bool,
                             res: ForensicsRunResult) -> bool:
    """POST (or print, in dry-run) one proposal. Returns True on success."""
    if dry_run:
        print("[dry-run] proposal:")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        res.proposed += 1
        return True
    code, data = await _post(
        http, f"{java_base}/internal/supervisor/proposals", headers, body)
    if code != 200:
        res.errors.append(f"{body.get('action_type')}: proposals POST HTTP {code}")
        logger.warning("forensics: proposal POST failed (HTTP %s)", code)
        return False
    if isinstance(data, dict) and data.get("deduped"):
        res.deduped += 1
    else:
        res.proposed += 1
    return True


async def _deep_dive_pass(http: Any, java_base: str, headers: dict,
                          hotspots: list[Hotspot], *, cap: int,
                          dry_run: bool, supersede_map: Optional[dict],
                          force_client: Any,
                          res: ForensicsRunResult) -> None:
    if not hotspots or cap <= 0:
        return
    client = force_client or _haiku_client()
    res.llm_model = getattr(client, "model", "") or res.llm_model
    open_proposals = await _fetch_open_proposals(http, java_base, headers)

    for h in hotspots:
        if res.deep_dives >= cap or res.deep_dives >= MAX_DEEP_DIVES:
            break
        # Activity-id dedupe BEFORE the LLM call: if an open proposal on the
        # same block already cites >= 1 of these traces, the evidence is the
        # same — skip the whole dive (no LLM cost, no duplicate proposal).
        activity_ids = h.activity_ids
        dup_id = find_activity_dedupe(h.block, activity_ids, open_proposals)
        if dup_id is not None:
            res.deduped += 1
            logger.info(
                "forensics: open proposal #%s already covers block=%s with "
                "overlapping activity ids %s — skip (evidence unchanged)",
                dup_id, h.block, activity_ids)
            continue
        block_doc = await _fetch_block_doc(http, java_base, headers, h.block)
        summaries = _load_hotspot_summaries(h)
        try:
            resp = await client.create(
                system=_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": build_deepdive_prompt(h, summaries, block_doc),
                }],
                max_tokens=2500,
            )
        except Exception as ex:  # noqa: BLE001 — one bad call must not kill the run
            res.deep_dives += 1
            res.errors.append(f"deep-dive {h.block}: LLM call failed: {ex}")
            logger.warning("forensics: deep-dive LLM call failed for %s: %s",
                           h.block, ex)
            continue
        res.deep_dives += 1
        res.input_tokens += getattr(resp, "input_tokens", 0) or 0
        res.output_tokens += getattr(resp, "output_tokens", 0) or 0

        diagnosis = _safe_parse_json(getattr(resp, "text", "") or "")
        err = validate_diagnosis(diagnosis)
        if err:
            res.skipped_invalid += 1
            logger.info("forensics: skip invalid diagnosis for %s (%s)",
                        h.block, err)
            continue
        decision = decide_action(h, diagnosis)
        if decision is None:
            res.skipped_gated += 1
            continue
        narrative = compose_forensics_narrative(h, diagnosis,
                                                decision["action_type"])
        meta = {
            "source": "supervisor_forensics",
            "model": res.llm_model,
            "block": h.block,
            "distinct_requests": h.distinct_request_count,
            "reject_count": h.reject_count,
            "loop_signals": h.loop_signals,
            "activity_ids": activity_ids,
        }
        supersedes = resolve_supersede(decision["action_type"], h.block,
                                       supersede_map, open_proposals)
        body = _proposal_body(decision["action_type"], decision["proposal"],
                              narrative, decision["rationale"], meta, supersedes)
        await _dispatch_proposal(http, java_base, headers, body,
                                 dry_run=dry_run, res=res)


def _load_hotspot_summaries(h: Hotspot) -> list[str]:
    """Compact summaries for the deep-dive prompt: worst traces first
    (failed_ish, then most rejects on this block)."""
    ordered = sorted(
        h.signals,
        key=lambda s: (not s.failed_ish, -s.rejects_by_block.get(h.block, 0)),
    )
    out: list[str] = []
    for s in ordered[:MAX_SUMMARIES_PER_DIVE]:
        try:
            trace = json.loads(Path(s.path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as ex:
            logger.warning("forensics: cannot re-read trace %s: %s", s.path, ex)
            continue
        out.append(compact_trace_summary(trace))
    return out


async def _cfg_pass(http: Any, java_base: str, headers: dict, *,
                    state_file: str, dry_run: bool, now: datetime,
                    res: ForensicsRunResult) -> None:
    code, data = await _get(http, f"{java_base}/internal/llm-usage/daily",
                            headers, params={"days": 1})
    if code != 200:
        logger.info("forensics: llm-usage daily unavailable (HTTP %s) — "
                    "skip CFG pass", code)
        return
    findings = cfg_findings(normalize_daily_rows(data))
    if not findings:
        return
    state = load_state(state_file)
    day = now.strftime("%Y-%m-%d")
    state_dirty = False
    for f in findings:
        if cfg_already_posted(state, day, f["model"]):
            res.cfg_deduped += 1
            logger.info("forensics: CFG for %s already posted today — skip",
                        f["model"])
            continue
        narrative = compose_cfg_narrative(f)
        f = {**f, "display_title": (
            f"[{f.get('model','?')}] 空回應率異常 — 建議調整 provider")[:48]}
        body = _proposal_body(
            "CFG", f, narrative,
            rationale=narrative["happened"],
            meta={"source": "supervisor_forensics", "kind": "cfg", "day": day,
                  "activity_ids": [f"llm-daily:{day}:{f['model']}"]},
            supersedes=None,
        )
        if dry_run:
            print("[dry-run] CFG proposal:")
            print(json.dumps(body, ensure_ascii=False, indent=2))
            res.cfg_proposed += 1
            continue  # dry-run never touches the state file
        code2, _ = await _post(
            http, f"{java_base}/internal/supervisor/proposals", headers, body)
        if code2 != 200:
            res.errors.append(f"CFG {f['model']}: proposals POST HTTP {code2}")
            continue
        res.cfg_proposed += 1
        mark_cfg_posted(state, day, f["model"])
        state_dirty = True
    if state_dirty:
        save_state(state_file, state)


async def _verify_pass(http: Any, java_base: str, headers: dict, *,
                       trace_dir: Path, dry_run: bool, now: datetime,
                       res: ForensicsRunResult) -> None:
    code, rows = await _get(
        http, f"{java_base}/internal/supervisor/verify-queue", headers)
    if code != 200 or not isinstance(rows, list):
        logger.info("forensics: verify-queue unavailable (HTTP %s) — "
                    "skip verify pass", code)
        return
    if not rows:
        return
    # Windows straddle landed_at, which can predate the selection window —
    # scan the whole dir (days=None).
    all_signals = load_traces(trace_dir, days=None, now=now)
    daily_rows: Optional[list[dict]] = None

    for row in rows:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        rid = row["id"]
        action_type = str(row.get("action_type") or "")
        prop = row.get("proposal")
        if isinstance(prop, str):
            try:
                prop = json.loads(prop)
            except json.JSONDecodeError:
                prop = {}
        if not isinstance(prop, dict):
            prop = {}

        result: Optional[str] = None
        if action_type == "DOC_REVISE":
            block = str(prop.get("block_id") or "").strip()
            landed = _parse_dt(row.get("landed_at"))
            if block and landed:
                result = compose_doc_verify_result(block, all_signals, landed)
            else:
                result = "insufficient data"
        elif action_type == "CFG":
            model = str(prop.get("model") or "").strip()
            if daily_rows is None:
                code2, d2 = await _get(
                    http, f"{java_base}/internal/llm-usage/daily", headers,
                    params={"days": 1})
                daily_rows = normalize_daily_rows(d2) if code2 == 200 else []
            if model:
                try:
                    before_rate = float(prop.get("empty_rate") or 0.0)
                except (TypeError, ValueError):
                    before_rate = 0.0
                result = compose_cfg_verify_result(model, before_rate, daily_rows)
            else:
                result = "insufficient data"
        if result is None:
            continue  # action types this pass doesn't know how to verify

        if dry_run:
            print(f"[dry-run] verify #{rid}: {result}")
            res.verified += 1
            continue
        code3, _ = await _post(
            http, f"{java_base}/internal/supervisor/proposals/{rid}/verify",
            headers, {"verify_result": result})
        if code3 == 200:
            res.verified += 1
        else:
            # The verify endpoint is part of the Java W3 workstream — a 404
            # here just means it hasn't landed; log, don't error.
            logger.info("forensics: verify POST for #%s returned HTTP %s — skip",
                        rid, code3)


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def run_forensics(
    java_base: str,
    internal_token: str,
    *,
    trace_dir: str | Path = DEFAULT_TRACE_DIR,
    days: int = DEFAULT_DAYS,
    dry_run: bool = False,
    max_deep_dives: int = MAX_DEEP_DIVES,
    state_file: str = DEFAULT_STATE_FILE,
    supersede_map: Optional[dict] = None,
    force_client: Any = None,
    now: Optional[datetime] = None,
) -> ForensicsRunResult:
    """One offline forensics pass. See module docstring for the pipeline."""
    import httpx

    now = now or datetime.now(tz=timezone.utc)
    res = ForensicsRunResult()
    headers = {"X-Internal-Token": internal_token}
    java_base = java_base.rstrip("/")
    trace_dir = Path(trace_dir)

    signals = load_traces(trace_dir, days=days, now=now)
    res.traces_scanned = len(signals)
    res.failed_traces = sum(1 for s in signals if s.failed_ish)
    hotspots, dropped = aggregate_hotspots(signals)
    res.hotspots = len(hotspots)
    res.dropped_single_case = len(dropped)

    cap = max(0, min(int(max_deep_dives), MAX_DEEP_DIVES))

    async with httpx.AsyncClient(timeout=30.0) as http:
        await _deep_dive_pass(
            http, java_base, headers, hotspots,
            cap=cap, dry_run=dry_run, supersede_map=supersede_map,
            force_client=force_client, res=res,
        )
        await _cfg_pass(
            http, java_base, headers,
            state_file=state_file, dry_run=dry_run, now=now, res=res,
        )
        await _verify_pass(
            http, java_base, headers,
            trace_dir=trace_dir, dry_run=dry_run, now=now, res=res,
        )
    return res
