"""Supervisor trace-forensics tests (W3) — no network, no LLM.

Covers: selection signals, hotspot aggregation + F3 anti-pollution gate,
diagnosis validation + decision tree, narrative composition, CFG threshold
+ same-day dedupe, verify-string computation, and the full run loop with a
fake Java (defensive against not-yet-landed W3 endpoints) + stubbed LLM.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from python_ai_sidecar.supervisor_forensics.forensics import (
    CFG_EMPTY_RATE_THRESHOLD,
    CFG_MIN_CALLS,
    KNOWLEDGE_MIN_DISTINCT,
    LOOP_INSPECT_THRESHOLD,
    MAX_DEEP_DIVES,
    Hotspot,
    TraceSignals,
    aggregate_hotspots,
    cfg_already_posted,
    cfg_findings,
    compact_trace_summary,
    compose_cfg_narrative,
    compose_cfg_verify_result,
    compose_doc_verify_result,
    compose_forensics_narrative,
    decide_action,
    extract_signals,
    load_state,
    load_traces,
    mark_cfg_posted,
    resolve_supersede,
    run_forensics,
    validate_diagnosis,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


# ── fixtures ─────────────────────────────────────────────────────────────

def make_trace(instruction: str, *, status: str = "finished",
               rejects: dict | None = None, inspects: dict | None = None,
               round_max: int = 0, escalated: bool = False,
               build_id: str = "t1", started_at: str | None = None,
               with_verifier_decisions: bool = True) -> dict:
    steps: list = []
    verifier: list = []
    records: list = []
    for block, n in (rejects or {}).items():
        for _ in range(n):
            if with_verifier_decisions:
                verifier.append({
                    "phase_id": "p1", "phase_expected": "table",
                    "candidate_block": block, "candidate_block_covers": [],
                    "comparison": {"result": "no_expected"},
                    "verdict": "no_match",
                })
            steps.append({"node": "phase_verifier", "status": "no_match",
                          "phase_id": "p1", "block_id": block})
    for block, n in (inspects or {}).items():
        for _ in range(n):
            records.append({
                "node": "agentic_phase_loop", "phase_id": "p1",
                "llm_response": {
                    "text_blocks": [],
                    "tool_use": {"name": "inspect_block_doc",
                                 "input": {"block_id": block}},
                },
            })
    for _ in range(round_max):
        steps.append({"node": "agentic_phase_loop", "status": "round_max_hit",
                      "phase_id": "p1"})
    if escalated:
        steps.append({"node": "agentic_phase_loop",
                      "status": "empty_response_escalated", "phase_id": "p1"})
    return {
        "build_id": build_id,
        "instruction": instruction,
        "status": status,
        "started_at": started_at,
        "graph_steps": steps,
        "llm_calls": [],
        "decision_records": records,
        "verifier_decisions": verifier,
        "final_pipeline": {"nodes": [], "edges": []},
    }


def write_trace(dirpath: Path, name: str, trace: dict,
                mtime: float | None = None) -> Path:
    p = dirpath / name
    p.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def sig(instruction: str, *, rejects: dict | None = None,
        inspects: dict | None = None, failed: bool = True,
        path: str = "trace.json", started_at: str | None = None,
        mtime: float = 0.0) -> TraceSignals:
    rejects = rejects or {}
    return TraceSignals(
        path=path, build_id="b", instruction=instruction,
        status="failed" if failed else "finished", failed_ish=failed,
        round_max_hits=0, empty_response_escalated=False, rounds_used=0,
        rejects_by_block=rejects, inspects_by_block=inspects or {},
        blocks_touched=list(rejects.keys()), started_at=started_at,
        mtime=mtime,
    )


DOC_GAP_DIAGNOSIS = {
    "root_cause_layer": "doc_gap",
    "diagnosis": "block 文件未說明 x_key 格式，導致 3 次拒絕",
    "doc_revision_draft": "x_key 必須是來源欄位名，不是顯示標籤",
    "knowledge_draft": None,
    "generalization": None,
}

PLANNING_DIAGNOSIS = {
    "root_cause_layer": "planning_knowledge",
    "diagnosis": "多個 request 都想全廠掃描但 plan 只放單機 source",
    "doc_revision_draft": None,
    "knowledge_draft": {"title": "全廠掃描先 list_objects 再 foreach",
                        "body": "Why: ... How to apply: ...",
                        "memo_class": "procedure", "applies_to": "plan"},
    "generalization": "涉及『所有機台』的 plan 必須以列舉 + foreach 開場",
}


# ── stage 1: selection ───────────────────────────────────────────────────

def test_load_traces_mtime_window_and_bad_files(tmp_path):
    ts_now = NOW.timestamp()
    write_trace(tmp_path, "fresh.json", make_trace("q1", status="failed"),
                mtime=ts_now - 86400)                     # 1d old — in
    write_trace(tmp_path, "old.json", make_trace("q2", status="failed"),
                mtime=ts_now - 10 * 86400)                # 10d old — out
    (tmp_path / "corrupt.json").write_text("{not json", encoding="utf-8")
    os.utime(tmp_path / "corrupt.json", (ts_now, ts_now))

    out = load_traces(tmp_path, days=7, now=NOW)
    assert [s.ref for s in out] == ["fresh.json"]
    # days=None disables the window (verify pass needs older traces)
    assert {s.ref for s in load_traces(tmp_path, days=None, now=NOW)} == \
        {"fresh.json", "old.json"}


def test_load_traces_missing_dir_is_empty(tmp_path):
    assert load_traces(tmp_path / "nope", days=7, now=NOW) == []


@pytest.mark.parametrize("kwargs,expect", [
    ({"status": "failed"}, True),
    ({"status": "handover_pending"}, True),
    ({"status": "finished", "escalated": True}, True),
    ({"status": "finished", "round_max": 1}, True),
    ({"status": "finished"}, False),
    ({"status": "success"}, False),
])
def test_failed_ish_variants(kwargs, expect):
    s = extract_signals(make_trace("q", **kwargs), "t.json")
    assert s.failed_ish is expect


def test_extract_rejects_from_verifier_decisions_no_double_count():
    # Both verifier_decisions AND mirroring phase_verifier steps present —
    # counts must come from verifier_decisions only (no doubling).
    t = make_trace("q", rejects={"block_a": 3, "block_b": 1})
    s = extract_signals(t, "t.json")
    assert s.rejects_by_block == {"block_a": 3, "block_b": 1}


def test_extract_rejects_fallback_graph_steps_for_legacy_trace():
    t = make_trace("q", rejects={"block_a": 2}, with_verifier_decisions=False)
    s = extract_signals(t, "t.json")
    assert s.rejects_by_block == {"block_a": 2}


def test_extract_inspects_and_blocks_touched():
    t = make_trace("q", rejects={"block_a": 1}, inspects={"block_a": 4})
    t["decision_records"].append({
        "node": "agentic_phase_loop",
        "llm_response": {"tool_use": {"name": "add_node",
                                      "input": {"block_name": "block_c"}}},
        "decision_metadata": {"actual_pick": "block_d"},
    })
    s = extract_signals(t, "t.json")
    assert s.inspects_by_block == {"block_a": 4}
    assert "block_a" in s.blocks_touched
    assert "block_c" in s.blocks_touched
    assert "block_d" in s.blocks_touched


# ── stage 2: hotspot aggregation + F3 gate ──────────────────────────────

def test_f3_gate_drops_single_request_hotspot():
    signals = [
        sig("req A", rejects={"block_x": 2}),
        sig("req B", rejects={"block_x": 1}),
        sig("req C", rejects={"block_solo": 4}),   # one distinct request only
        sig("req C 再一次", rejects={}),            # no signal on block_solo
    ]
    kept, dropped = aggregate_hotspots(signals)
    assert [h.block for h in kept] == ["block_x"]
    assert len(dropped) == 1
    assert dropped[0]["block"] == "block_solo"
    assert dropped[0]["reject_count"] == 4         # logged, not proposed


def test_hotspot_ranking_distinct_then_rejects():
    signals = [
        sig("r1", rejects={"block_two": 9}),
        sig("r2", rejects={"block_two": 9}),
        sig("r1", rejects={"block_three": 1}),
        sig("r2", rejects={"block_three": 1}),
        sig("r3", rejects={"block_three": 1}),
    ]
    kept, _ = aggregate_hotspots(signals)
    # distinct wins over raw reject volume
    assert [h.block for h in kept] == ["block_three", "block_two"]
    assert kept[0].distinct_request_count == 3
    assert kept[1].reject_count == 18


def test_repeated_inspects_alone_form_hotspot_and_loop_signals():
    signals = [
        sig("r1", inspects={"block_loop": LOOP_INSPECT_THRESHOLD}, failed=False),
        sig("r2", inspects={"block_loop": LOOP_INSPECT_THRESHOLD + 1}, failed=False),
        # below threshold — must NOT create membership
        sig("r3", inspects={"block_loop": LOOP_INSPECT_THRESHOLD - 1}, failed=False),
    ]
    kept, _ = aggregate_hotspots(signals)
    assert [h.block for h in kept] == ["block_loop"]
    assert len(kept[0].signals) == 2
    assert kept[0].loop_signals == 2


# ── stage 3: diagnosis validation ────────────────────────────────────────

def test_validate_diagnosis_gates():
    assert validate_diagnosis(DOC_GAP_DIAGNOSIS) is None
    assert validate_diagnosis(PLANNING_DIAGNOSIS) is None
    assert "not a JSON object" in validate_diagnosis(None)
    assert "unknown root_cause_layer" in validate_diagnosis(
        {"root_cause_layer": "vibes", "diagnosis": "x"})
    assert "doc_revision_draft" in validate_diagnosis(
        {"root_cause_layer": "doc_gap", "diagnosis": "x"})
    assert "knowledge_draft" in validate_diagnosis(
        {"root_cause_layer": "planning_knowledge", "diagnosis": "x"})
    bad_class = json.loads(json.dumps(PLANNING_DIAGNOSIS))
    bad_class["knowledge_draft"]["memo_class"] = "preference"
    assert "domain|procedure" in validate_diagnosis(bad_class)
    no_gen = json.loads(json.dumps(PLANNING_DIAGNOSIS))
    no_gen["generalization"] = ""
    assert "generalization" in validate_diagnosis(no_gen)


# ── stage 4: decision tree + narrative ──────────────────────────────────

def _hotspot(n_distinct: int, *, block: str = "block_x",
             rejects_per: int = 2) -> Hotspot:
    h = Hotspot(block=block)
    for i in range(n_distinct):
        h.signals.append(sig(f"request {i}", rejects={block: rejects_per},
                             path=f"t{i}.json"))
    return h


def test_decide_doc_gap_maps_to_doc_revise():
    h = _hotspot(2)
    d = decide_action(h, DOC_GAP_DIAGNOSIS)
    assert d["action_type"] == "DOC_REVISE"
    assert d["proposal"]["block_id"] == "block_x"
    assert d["proposal"]["revised_doc_draft"] == DOC_GAP_DIAGNOSIS["doc_revision_draft"]
    assert d["proposal"]["trace_refs"] == ["t0.json", "t1.json"]


def test_decide_planning_knowledge_needs_three_distinct():
    # 2 distinct requests → 泛化門檻未過 → nothing
    assert decide_action(_hotspot(KNOWLEDGE_MIN_DISTINCT - 1),
                         PLANNING_DIAGNOSIS) is None
    d = decide_action(_hotspot(KNOWLEDGE_MIN_DISTINCT), PLANNING_DIAGNOSIS)
    assert d["action_type"] == "PROMOTE"
    assert d["proposal"]["memo_class"] == "procedure"
    assert d["proposal"]["generalization"] == PLANNING_DIAGNOSIS["generalization"]
    assert len(d["proposal"]["trace_refs"]) == KNOWLEDGE_MIN_DISTINCT


def test_decide_code_suspect_and_inconclusive():
    d = decide_action(_hotspot(2), {
        "root_cause_layer": "code_suspect",
        "diagnosis": "文件正確但 preview rows 永遠 0",
    })
    assert d["action_type"] == "ISSUE"
    assert d["proposal"]["summary"].startswith("文件正確")
    assert "block_x" in d["proposal"]["suspect"]
    assert d["proposal"]["trace_refs"]
    assert decide_action(_hotspot(2), {
        "root_cause_layer": "inconclusive", "diagnosis": "看不出來",
    }) is None


def test_narrative_happened_format_and_four_keys():
    h = Hotspot(block="block_x")
    h.signals = [
        sig("r1", rejects={"block_x": 2}),
        sig("r2", rejects={"block_x": 1}),
        sig("r3", rejects={"block_x": 1}, inspects={"block_x": 3}),
        sig("r3", rejects={"block_x": 1}, inspects={"block_x": 4}),
    ]
    # rejects=5, loop_signals=2 (two traces with inspects >= threshold)
    n = compose_forensics_narrative(h, DOC_GAP_DIAGNOSIS, "DOC_REVISE")
    assert set(n) == {"happened", "observed", "subject", "action"}
    assert n["happened"] == "3 個 request 在 block_x 累積 7 次拒/迴圈訊號（trace ×4）"
    assert n["observed"] == DOC_GAP_DIAGNOSIS["diagnosis"]
    assert n["subject"] == {"kind": "block", "id": "block_x", "label": "block_x"}
    assert "block_x" in n["action"]


def test_promote_narrative_mentions_distinct_and_generalization():
    h = _hotspot(3)
    n = compose_forensics_narrative(h, PLANNING_DIAGNOSIS, "PROMOTE")
    assert "3 個 request" in n["happened"]
    assert "泛化：" in n["happened"]
    assert PLANNING_DIAGNOSIS["generalization"] in n["happened"]
    assert "3 個 distinct request" in n["action"]
    assert "procedure" in n["action"]


def test_resolve_supersede_map_and_open_list():
    open_props = [
        {"id": 7, "action_type": "DOC_REVISE",
         "proposal": json.dumps({"block_id": "block_x"})},
        {"id": 9, "action_type": "ISSUE",
         "narrative": json.dumps({"subject": {"id": "block_y"}})},
    ]
    # map wins, action-scoped key wins over bare key
    assert resolve_supersede("DOC_REVISE", "block_x",
                             {"DOC_REVISE:block_x": 3, "block_x": 4},
                             open_props) == 3
    assert resolve_supersede("DOC_REVISE", "block_x", {"block_x": 4},
                             open_props) == 4
    # open list fallback: match action_type + subject
    assert resolve_supersede("DOC_REVISE", "block_x", None, open_props) == 7
    assert resolve_supersede("ISSUE", "block_y", None, open_props) == 9
    assert resolve_supersede("DOC_REVISE", "block_zzz", None, open_props) is None
    assert resolve_supersede("DOC_REVISE", "block_x", None, None) is None


# ── stage 5: CFG threshold + dedupe ──────────────────────────────────────

def test_cfg_threshold_boundaries():
    rows = [
        {"model": "m/too-few", "calls": CFG_MIN_CALLS - 1, "empty_calls": 40},
        {"model": "m/at-threshold", "calls": 100,
         "empty_calls": int(100 * CFG_EMPTY_RATE_THRESHOLD)},   # exactly 20% — no
        {"model": "m/bad", "calls": 100, "empty_calls": 21},     # 21% — yes
        {"model": "", "calls": 500, "empty_calls": 400},         # no model — no
    ]
    out = cfg_findings(rows)
    assert [f["model"] for f in out] == ["m/bad"]
    assert out[0]["empty_rate"] == 0.21


def test_cfg_findings_accepts_alt_empty_key():
    out = cfg_findings([{"model": "m", "calls": 50, "empty": 20}])
    assert out and out[0]["empty_calls"] == 20


def test_cfg_narrative_format():
    n = compose_cfg_narrative({"model": "glm-5.2", "calls": 200,
                               "empty_calls": 50, "empty_rate": 0.25})
    assert n["happened"] == "glm-5.2 今日空回應率 25.0%（50/200）"
    assert n["subject"] == {"kind": "general", "id": "glm-5.2", "label": "glm-5.2"}
    assert n["observed"] == "provider 品質異常，重試放大成本"
    assert "人執行" in n["action"]


def test_cfg_state_dedupe_roundtrip(tmp_path):
    state_file = str(tmp_path / "state.json")
    state = load_state(state_file)
    assert state == {}
    assert not cfg_already_posted(state, "2026-07-06", "glm")
    mark_cfg_posted(state, "2026-07-06", "glm")
    assert cfg_already_posted(state, "2026-07-06", "glm")
    # next day: old entries pruned, model postable again
    mark_cfg_posted(state, "2026-07-07", "other")
    assert not cfg_already_posted(state, "2026-07-07", "glm")
    assert "2026-07-06" not in state["cfg_posted"]


# ── stage 6: verify strings ──────────────────────────────────────────────

def test_doc_verify_string_before_after():
    landed = NOW - timedelta(days=3)
    signals = [
        sig("r1", rejects={"block_x": 3},
            started_at=(landed - timedelta(days=2)).isoformat()),
        sig("r2", rejects={"block_x": 2},
            started_at=(landed - timedelta(days=1)).isoformat()),
        sig("r3", rejects={"block_x": 1},
            started_at=(landed + timedelta(days=1)).isoformat()),
        # outside both windows — ignored
        sig("r4", rejects={"block_x": 9},
            started_at=(landed - timedelta(days=20)).isoformat()),
    ]
    assert compose_doc_verify_result("block_x", signals, landed) == \
        "拒因 block_x 5→1（7d 窗）"


def test_doc_verify_insufficient_data():
    landed = NOW - timedelta(days=3)
    signals = [sig("r1", rejects={"other_block": 2},
                   started_at=NOW.isoformat())]
    assert compose_doc_verify_result("block_x", signals, landed) == \
        "insufficient data"


def test_cfg_verify_string_and_insufficient():
    rows = [{"model": "glm", "calls": 100, "empty_calls": 5}]
    assert compose_cfg_verify_result("glm", 0.25, rows) == \
        "glm 空回應率 25.0%→5.0%（daily）"
    assert compose_cfg_verify_result("missing-model", 0.25, rows) == \
        "insufficient data"
    assert compose_cfg_verify_result("glm", 0.25, []) == "insufficient data"


# ── compact summary budget ───────────────────────────────────────────────

def test_compact_trace_summary_respects_budget():
    t = make_trace("很長的需求 " * 50, rejects={"block_a": 5})
    s = compact_trace_summary(t, budget=500)
    assert len(s) <= 500 + len("…[truncated]")
    full = compact_trace_summary(t)
    assert "block_a" in full


# ── full run: fake Java + stub LLM ───────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        return {"data": self._data}


class _FakeJava:
    """Fake httpx.AsyncClient — routes keyed by URL substring. Defaults to
    404 for everything (the not-yet-landed W3 endpoints)."""

    def __init__(self):
        self.get_routes: dict[str, tuple[int, object]] = {}
        self.posted: list[tuple[str, dict]] = []
        self.post_status = 200

    def client_factory(self):
        fake = self

        class _Client:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, params=None):
                for key, (status, data) in fake.get_routes.items():
                    if key in url:
                        return _FakeResp(status, data)
                return _FakeResp(404, None)

            async def post(self, url, json=None, headers=None):
                fake.posted.append((url, json))
                return _FakeResp(fake.post_status,
                                 {"id": len(fake.posted), "deduped": False})

        return _Client


class _StubResp:
    def __init__(self, text):
        self.text = text
        self.input_tokens = 100
        self.output_tokens = 50


class _StubLLM:
    model = "stub-model"

    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    async def create(self, **kw):
        self.calls += 1
        return _StubResp(json.dumps(self._payload, ensure_ascii=False))


class _MustNotCallLLM:
    model = "must-not-call"
    calls = 0

    async def create(self, **kw):  # pragma: no cover
        pytest.fail("LLM must not be called")


def _patch_httpx(monkeypatch, fake: _FakeJava):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", fake.client_factory())


def _seed_hotspot_traces(tmp_path: Path, blocks: list[str],
                         n_requests: int = 2) -> None:
    ts = NOW.timestamp()
    for i in range(n_requests):
        rejects = {b: 2 for b in blocks}
        write_trace(tmp_path, f"trace{i}.json",
                    make_trace(f"request {i}", status="handover_pending",
                               rejects=rejects, build_id=f"b{i}",
                               started_at=NOW.isoformat()),
                    mtime=ts - 3600 * (i + 1))


def test_run_end_to_end_posts_doc_revise(tmp_path, monkeypatch):
    fake = _FakeJava()
    _patch_httpx(monkeypatch, fake)
    _seed_hotspot_traces(tmp_path, ["block_a"])
    llm = _StubLLM(DOC_GAP_DIAGNOSIS)

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"), force_client=llm))

    assert res.traces_scanned == 2 and res.failed_traces == 2
    assert res.hotspots == 1 and res.deep_dives == 1 and res.proposed == 1
    assert not res.errors
    urls = [u for u, _ in fake.posted]
    assert urls == ["http://java/internal/supervisor/proposals"]
    body = fake.posted[0][1]
    assert body["action_type"] == "DOC_REVISE"
    prop = json.loads(body["proposal"])            # json string round-trips
    assert prop["block_id"] == "block_a"
    assert prop["trace_refs"] == ["trace0.json", "trace1.json"]
    nar = json.loads(body["narrative"])
    assert set(nar) == {"happened", "observed", "subject", "action"}
    assert body["proposer_meta"]["source"] == "supervisor_forensics"
    assert "supersedes" not in body                # proposals-open 404'd


def test_run_hard_caps_llm_calls_at_three(tmp_path, monkeypatch):
    fake = _FakeJava()
    _patch_httpx(monkeypatch, fake)
    # 5 hotspots, each with 2 distinct requests → only MAX_DEEP_DIVES dives
    _seed_hotspot_traces(tmp_path, [f"block_{c}" for c in "abcde"])
    llm = _StubLLM(DOC_GAP_DIAGNOSIS)

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"), force_client=llm,
        max_deep_dives=99))                        # caller cannot raise the cap
    assert llm.calls == MAX_DEEP_DIVES
    assert res.deep_dives == MAX_DEEP_DIVES
    assert res.hotspots == 5


def test_run_f3_gate_single_case_produces_nothing(tmp_path, monkeypatch):
    fake = _FakeJava()
    _patch_httpx(monkeypatch, fake)
    write_trace(tmp_path, "only.json",
                make_trace("唯一的 request", status="failed",
                           rejects={"block_a": 6}),
                mtime=NOW.timestamp() - 60)
    llm = _MustNotCallLLM()

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"), force_client=llm))
    assert res.hotspots == 0
    assert res.dropped_single_case == 1
    assert res.proposed == 0
    assert fake.posted == []


def test_run_planning_gate_logs_and_skips(tmp_path, monkeypatch):
    fake = _FakeJava()
    _patch_httpx(monkeypatch, fake)
    _seed_hotspot_traces(tmp_path, ["block_a"], n_requests=2)  # 2 < 3 distinct
    llm = _StubLLM(PLANNING_DIAGNOSIS)

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"), force_client=llm))
    assert res.deep_dives == 1
    assert res.skipped_gated == 1 and res.proposed == 0
    assert fake.posted == []


def test_run_invalid_llm_json_is_skipped_not_crash(tmp_path, monkeypatch):
    fake = _FakeJava()
    _patch_httpx(monkeypatch, fake)
    _seed_hotspot_traces(tmp_path, ["block_a"])

    class _Garbage:
        model = "garbage"

        async def create(self, **kw):
            return _StubResp("not json at all")

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"), force_client=_Garbage()))
    assert res.skipped_invalid == 1 and res.proposed == 0
    assert fake.posted == []


def test_run_supersede_from_open_proposals(tmp_path, monkeypatch):
    fake = _FakeJava()
    fake.get_routes["proposals-open"] = (200, [
        {"id": 42, "action_type": "DOC_REVISE",
         "proposal": json.dumps({"block_id": "block_a"})},
    ])
    _patch_httpx(monkeypatch, fake)
    _seed_hotspot_traces(tmp_path, ["block_a"])

    asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"),
        force_client=_StubLLM(DOC_GAP_DIAGNOSIS)))
    assert fake.posted[0][1]["supersedes"] == 42


def test_run_cfg_pass_posts_and_dedupes(tmp_path, monkeypatch):
    fake = _FakeJava()
    fake.get_routes["llm-usage/daily"] = (200, [
        {"model": "glm-5.2", "calls": 200, "empty_calls": 60},   # 30% — fires
        {"model": "haiku", "calls": 200, "empty_calls": 10},     # 5% — quiet
    ])
    _patch_httpx(monkeypatch, fake)
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    state_file = str(tmp_path / "state.json")

    res1 = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=trace_dir, now=NOW,
        state_file=state_file, force_client=_MustNotCallLLM()))
    assert res1.cfg_proposed == 1 and res1.cfg_deduped == 0
    body = fake.posted[0][1]
    assert body["action_type"] == "CFG"
    prop = json.loads(body["proposal"])
    assert prop == {"model": "glm-5.2", "calls": 200,
                    "empty_calls": 60, "empty_rate": 0.3}
    nar = json.loads(body["narrative"])
    assert nar["happened"] == "glm-5.2 今日空回應率 30.0%（60/200）"

    # same-day second run: deduped via state file, no new POST
    res2 = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=trace_dir, now=NOW,
        state_file=state_file, force_client=_MustNotCallLLM()))
    assert res2.cfg_proposed == 0 and res2.cfg_deduped == 1
    assert len(fake.posted) == 1


def test_run_verify_pass_posts_verify_result(tmp_path, monkeypatch):
    landed = NOW - timedelta(days=2)
    fake = _FakeJava()
    fake.get_routes["verify-queue"] = (200, [
        {"id": 5, "action_type": "DOC_REVISE",
         "proposal": json.dumps({"block_id": "block_a"}),
         "landed_at": landed.isoformat()},
        {"id": 6, "action_type": "CFG",
         "proposal": json.dumps({"model": "glm", "empty_rate": 0.30})},
    ])
    fake.get_routes["llm-usage/daily"] = (200, [
        {"model": "glm", "calls": 100, "empty_calls": 4},
    ])
    _patch_httpx(monkeypatch, fake)
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    ts = NOW.timestamp()
    write_trace(trace_dir, "before.json",
                make_trace("r1", status="failed", rejects={"block_a": 4},
                           started_at=(landed - timedelta(days=1)).isoformat()),
                mtime=ts - 86400 * 3)
    # same instruction as before.json → F3-gated, so no deep-dive LLM call;
    # the verify windows only care about timestamps + reject counts.
    write_trace(trace_dir, "after.json",
                make_trace("r1", status="finished", rejects={"block_a": 1},
                           started_at=(landed + timedelta(days=1)).isoformat()),
                mtime=ts - 86400)

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=trace_dir, now=NOW,
        state_file=str(tmp_path / "state.json"),
        force_client=_MustNotCallLLM()))
    # CFG daily fires too (glm 4% is quiet) — filter verify POSTs
    verify_posts = [(u, b) for u, b in fake.posted if u.endswith("/verify")]
    assert len(verify_posts) == 2
    by_id = {u: b for u, b in verify_posts}
    assert by_id["http://java/internal/supervisor/proposals/5/verify"] == \
        {"verify_result": "拒因 block_a 4→1（7d 窗）"}
    assert by_id["http://java/internal/supervisor/proposals/6/verify"] == \
        {"verify_result": "glm 空回應率 30.0%→4.0%（daily）"}
    assert res.verified == 2


def test_run_all_w3_endpoints_404_is_graceful(tmp_path, monkeypatch):
    """proposals-open / llm-usage daily / verify-queue all missing (the Java
    W3 workstream hasn't landed) — run completes with zero errors."""
    fake = _FakeJava()                     # every GET 404s by default
    _patch_httpx(monkeypatch, fake)
    _seed_hotspot_traces(tmp_path, ["block_a"])

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW,
        state_file=str(tmp_path / "state.json"),
        force_client=_StubLLM(DOC_GAP_DIAGNOSIS)))
    assert not res.errors
    assert res.proposed == 1               # deep-dive still works
    assert res.cfg_proposed == 0 and res.verified == 0


def test_run_dry_run_never_posts_or_touches_state(tmp_path, monkeypatch, capsys):
    fake = _FakeJava()
    fake.get_routes["llm-usage/daily"] = (200, [
        {"model": "glm", "calls": 100, "empty_calls": 30},
    ])
    _patch_httpx(monkeypatch, fake)
    _seed_hotspot_traces(tmp_path, ["block_a"])
    state_file = tmp_path / "state.json"

    res = asyncio.run(run_forensics(
        "http://java", "tok", trace_dir=tmp_path, now=NOW, dry_run=True,
        state_file=str(state_file), force_client=_StubLLM(DOC_GAP_DIAGNOSIS)))
    assert res.proposed == 1 and res.cfg_proposed == 1
    assert fake.posted == []               # nothing hit the wire
    assert not state_file.exists()         # dry-run never persists dedupe
    out = capsys.readouterr().out
    assert "DOC_REVISE" in out and "CFG" in out
