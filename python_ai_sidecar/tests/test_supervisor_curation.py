"""Supervisor curation proposer tests (Phase 5).

Focus: the deterministic validation gate (untrusted LLM output → only
well-formed proposals with real ids pass) and the full run loop with a fake
LLM + fake Java (propose-only: only POST /proposals, never a mutation call).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from python_ai_sidecar.supervisor_curation.proposer import (
    MAX_PROPOSALS_PER_RUN,
    agents_for_proposal,
    build_user_prompt,
    compose_narrative,
    run_curation,
    validate_proposal,
)

K_IDS = {10, 11, 12, 20}
M_IDS = {40, 41}


# ── validate_proposal ────────────────────────────────────────────────────

def test_validate_merge_ok_and_bad():
    ok = {"action_type": "MERGE",
          "proposal": {"keep_id": 10, "remove_ids": [11, 12]}}
    assert validate_proposal(ok, K_IDS, M_IDS) is None
    # keep in removes
    bad = {"action_type": "MERGE", "proposal": {"keep_id": 10, "remove_ids": [10]}}
    assert "must not be in" in validate_proposal(bad, K_IDS, M_IDS)
    # hallucinated id
    halluc = {"action_type": "MERGE", "proposal": {"keep_id": 10, "remove_ids": [999]}}
    assert "unknown knowledge ids" in validate_proposal(halluc, K_IDS, M_IDS)


def test_validate_correct_requires_body_and_known_id():
    assert validate_proposal(
        {"action_type": "CORRECT",
         "proposal": {"target_id": 20, "new_body": "教訓 + Why + How"}},
        K_IDS, M_IDS) is None
    assert validate_proposal(
        {"action_type": "CORRECT", "proposal": {"target_id": 20, "new_body": " "}},
        K_IDS, M_IDS) is not None
    assert "unknown knowledge id" in validate_proposal(
        {"action_type": "CORRECT", "proposal": {"target_id": 777, "new_body": "x"}},
        K_IDS, M_IDS)


def test_validate_promote_class_gate():
    ok = {"action_type": "PROMOTE",
          "proposal": {"memo_class": "domain", "title": "t", "body": "b"}}
    assert validate_proposal(ok, K_IDS, M_IDS) is None
    # only domain|procedure — fast-path classes are NOT promotable this way
    bad = {"action_type": "PROMOTE",
           "proposal": {"memo_class": "preference", "title": "t", "body": "b"}}
    assert "domain|procedure" in validate_proposal(bad, K_IDS, M_IDS)


def test_validate_doc_revise_needs_draft_and_known_memos():
    ok = {"action_type": "DOC_REVISE",
          "proposal": {"block_id": "block_union", "memo_ids": [40, 41],
                       "revised_doc_draft": "..."}}
    assert validate_proposal(ok, K_IDS, M_IDS) is None
    assert "unknown memo ids" in validate_proposal(
        {"action_type": "DOC_REVISE",
         "proposal": {"block_id": "b", "memo_ids": [999], "revised_doc_draft": "d"}},
        K_IDS, M_IDS)
    assert "revised_doc_draft" in validate_proposal(
        {"action_type": "DOC_REVISE",
         "proposal": {"block_id": "b", "memo_ids": [40]}},
        K_IDS, M_IDS)


def test_validate_unknown_type():
    assert "unknown action_type" in validate_proposal(
        {"action_type": "NUKE", "proposal": {"x": 1}}, K_IDS, M_IDS)


# ── run loop (fake LLM + fake Java) ──────────────────────────────────────

class _FakeResp:
    def __init__(self, text: str):
        self.text = text
        self.input_tokens = 100
        self.output_tokens = 50


class _FakeLLM:
    def __init__(self, payload: dict):
        self._payload = payload

    async def create(self, **kw):
        return _FakeResp(json.dumps(self._payload, ensure_ascii=False))


def _patch_java(monkeypatch, curation_input: dict, posted: list):
    import httpx

    class _FakeHttpResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": self._data}

    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            assert "/internal/supervisor/curation-input" in url
            return _FakeHttpResp(curation_input)

        async def post(self, url, json=None, **kw):
            assert "/internal/supervisor/proposals" in url  # propose-only
            posted.append(json)
            return _FakeHttpResp({"id": len(posted), "deduped": False})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


CIN = {
    "draft_corrections": [{"id": 20, "title": "d", "body": "b",
                           "memo_class": "correction", "written_by": "planner"}],
    "live_preferences": [{"id": 10, "title": "p1", "body": "b",
                          "written_by": "builder"},
                         {"id": 11, "title": "p1-dup", "body": "b",
                          "written_by": "builder"}],
    "live_presentations": [],
    "pending_doc_memos": [{"id": 40, "block_id": "block_union", "memo": "m"}],
}


def test_run_curation_validates_and_posts_only_good(monkeypatch):
    posted: list = []
    _patch_java(monkeypatch, CIN, posted)
    llm = _FakeLLM({"proposals": [
        {"action_type": "MERGE", "target_ids": [10, 11],
         "proposal": {"keep_id": 10, "remove_ids": [11]}, "rationale": "同語意"},
        {"action_type": "PRUNE", "target_ids": [999],
         "proposal": {"target_ids": [999]}, "rationale": "hallucinated"},  # invalid
        {"action_type": "DOC_REVISE", "target_ids": [40],
         "proposal": {"block_id": "block_union", "memo_ids": [40],
                      "revised_doc_draft": "補上 union 的 port 說明"},
         "rationale": "doc gap"},
    ]})
    res = asyncio.run(run_curation("http://java", "tok", force_client=llm))
    assert res.proposed == 2
    assert res.skipped_invalid == 1
    assert len(posted) == 2
    assert {p["action_type"] for p in posted} == {"MERGE", "DOC_REVISE"}
    assert posted[0]["proposer_meta"]["model"]
    # attribution rides on every proposal's proposer_meta
    by_type = {p["action_type"]: p["proposer_meta"]["agents"] for p in posted}
    assert by_type["MERGE"] == ["builder"]   # rows 10 + 11 both builder-written
    assert by_type["DOC_REVISE"] == []       # block-doc memos aren't agent knowledge


def test_run_curation_caps_proposals(monkeypatch):
    posted: list = []
    _patch_java(monkeypatch, CIN, posted)
    many = [{"action_type": "CORRECT", "target_ids": [20],
             "proposal": {"target_id": 20, "new_body": f"note {i}"},
             "rationale": "r"} for i in range(MAX_PROPOSALS_PER_RUN + 5)]
    res = asyncio.run(run_curation("http://java", "tok",
                                   force_client=_FakeLLM({"proposals": many})))
    assert res.proposed == MAX_PROPOSALS_PER_RUN


def test_run_curation_bad_llm_output_is_error_not_crash(monkeypatch):
    posted: list = []
    _patch_java(monkeypatch, CIN, posted)

    class _Garbage:
        async def create(self, **kw):
            return _FakeResp("not json at all")

    res = asyncio.run(run_curation("http://java", "tok", force_client=_Garbage()))
    assert res.proposed == 0
    assert res.errors
    assert posted == []


def test_run_curation_empty_input_skips_llm(monkeypatch):
    posted: list = []
    empty = {"draft_corrections": [], "live_preferences": [],
             "live_presentations": [], "pending_doc_memos": []}
    _patch_java(monkeypatch, empty, posted)

    class _MustNotCall:
        async def create(self, **kw):  # pragma: no cover
            pytest.fail("LLM must not be called on empty input")

    res = asyncio.run(run_curation("http://java", "tok", force_client=_MustNotCall()))
    assert res.proposed == 0 and not res.errors


def test_posted_proposal_is_valid_json_string(monkeypatch):
    """W2 fix: `proposal` must be a json.dumps string (NOT str(dict) repr) so
    the DB-stored value round-trips via json.loads."""
    posted: list = []
    _patch_java(monkeypatch, CIN, posted)
    original = {"keep_id": 10, "remove_ids": [11], "merged_body": "合併後內容"}
    llm = _FakeLLM({"proposals": [
        {"action_type": "MERGE", "target_ids": [10, 11],
         "proposal": original, "rationale": "同語意"}]})
    res = asyncio.run(run_curation("http://java", "tok", force_client=llm))
    assert res.proposed == 1
    raw = posted[0]["proposal"]
    assert isinstance(raw, str)
    assert json.loads(raw) == original          # round-trip
    assert '"keep_id"' in raw                   # double-quoted JSON, not repr
    assert "'keep_id'" not in raw


def test_posted_narrative_four_sections(monkeypatch):
    """Every POST carries a deterministic 四段 narrative (jsonb on Java side)."""
    posted: list = []
    _patch_java(monkeypatch, CIN, posted)
    llm = _FakeLLM({"proposals": [
        {"action_type": "DOC_REVISE", "target_ids": [40],
         "proposal": {"block_id": "block_union", "memo_ids": [40],
                      "revised_doc_draft": "補上 union 的 port 說明"},
         "rationale": "doc gap"}]})
    asyncio.run(run_curation("http://java", "tok", force_client=llm))
    nar = json.loads(posted[0]["narrative"])    # valid JSON string
    assert set(nar) == {"happened", "observed", "subject", "action"}
    assert nar["subject"] == {"kind": "block", "id": "block_union",
                              "label": "block_union"}
    assert "1 筆" in nar["happened"]            # 案例數
    assert nar["observed"] == "doc gap"         # rationale becomes diagnosis
    assert "block_union" in nar["action"]


# ── compose_narrative per proposal type (deterministic, no LLM) ──────────

def test_narrative_merge():
    n = compose_narrative(
        {"action_type": "MERGE", "target_ids": [10, 11], "rationale": "",
         "proposal": {"keep_id": 10, "remove_ids": [11]}}, CIN)
    assert "2 筆" in n["happened"]
    assert n["subject"]["kind"] == "knowledge"
    assert n["subject"]["id"] == "10"
    assert n["subject"]["label"] == "p1"        # title looked up from input
    assert "#10" in n["action"] and "1 筆" in n["action"]
    assert n["observed"]                        # deterministic fallback used


def test_narrative_correct_promote_flag():
    n = compose_narrative(
        {"action_type": "CORRECT", "target_ids": [20], "rationale": "可蒸餾",
         "proposal": {"target_id": 20, "new_body": "x", "promote": True}}, CIN)
    assert "#20" in n["happened"] and "1 筆" in n["happened"]
    assert n["subject"] == {"kind": "knowledge", "id": "20", "label": "d"}
    assert "promote" in n["action"]
    assert n["observed"] == "可蒸餾"
    n2 = compose_narrative(
        {"action_type": "CORRECT",
         "proposal": {"target_id": 20, "new_body": "x", "promote": False}}, CIN)
    assert "draft" in n2["action"]


def test_narrative_prune_counts():
    n = compose_narrative(
        {"action_type": "PRUNE", "target_ids": [10, 11],
         "proposal": {"target_ids": [10, 11]}}, CIN)
    assert "2 筆" in n["happened"]
    assert n["subject"]["kind"] == "knowledge"
    assert n["subject"]["id"] == "10"
    assert "等 2 筆" in n["subject"]["label"]
    assert "停用 2 筆" in n["action"]


def test_narrative_promote_new_knowledge_has_no_subject_id():
    n = compose_narrative(
        {"action_type": "PROMOTE", "target_ids": [10, 20],
         "proposal": {"memo_class": "procedure", "title": "全廠掃描配方",
                      "body": "b"}}, CIN)
    assert "2 筆" in n["happened"]
    assert n["subject"]["kind"] == "knowledge"
    assert n["subject"]["id"] is None           # new row — no id yet
    assert n["subject"]["label"] == "全廠掃描配方"
    assert "procedure" in n["action"]


def test_build_user_prompt_contains_sections():
    p = build_user_prompt(CIN)
    assert "draft corrections" in p and "doc memos" in p
    assert "block_union" in p


# ── agents_for_proposal (originating-agent attribution) ──────────────────

# id → row (written_by is the only field the helper reads)
KIDX = {
    1: {"id": 1, "written_by": "builder"},
    2: {"id": 2, "written_by": "planner"},
    3: {"id": 3, "written_by": "builder"},
    4: {"id": 4, "written_by": "repair"},
    5: {"id": 5, "written_by": "human"},
    6: {"id": 6, "written_by": None},        # null → mapped out
    7: {"id": 7},                            # missing key → treated as null
}


def test_agents_merge_main_first_ordering():
    # rows 1(builder), 2(planner), 3(builder) → builder x2 (main) then planner
    agents = agents_for_proposal(
        "MERGE", {"proposal": {"keep_id": 1, "remove_ids": [2, 3]}}, KIDX)
    assert agents == ["builder", "planner"]


def test_agents_merge_ties_broken_by_first_seen():
    # planner(2) and repair(4) each once → tie → first-seen (keep_id first) wins
    agents = agents_for_proposal(
        "MERGE", {"proposal": {"keep_id": 2, "remove_ids": [4]}}, KIDX)
    assert agents == ["planner", "repair"]


def test_agents_correct_single():
    assert agents_for_proposal(
        "CORRECT", {"proposal": {"target_id": 4, "new_body": "x"}}, KIDX) == ["repair"]


def test_agents_prune_dedupes():
    # 1(builder) + 3(builder) + 2(planner) → dedupe builder, main-first
    assert agents_for_proposal(
        "PRUNE", {"proposal": {"target_ids": [1, 3, 2]}}, KIDX) == ["builder", "planner"]


def test_agents_human_kept_null_mapped_out():
    # 5(human) kept; 6(null) + 7(missing) dropped
    assert agents_for_proposal(
        "PRUNE", {"proposal": {"target_ids": [5, 6, 7]}}, KIDX) == ["human"]


def test_agents_promote_and_doc_revise_are_empty():
    assert agents_for_proposal(
        "PROMOTE", {"target_ids": [1, 2],
                    "proposal": {"memo_class": "domain", "title": "t", "body": "b"}},
        KIDX) == []
    assert agents_for_proposal(
        "DOC_REVISE", {"proposal": {"block_id": "b", "memo_ids": [40],
                                    "revised_doc_draft": "d"}}, KIDX) == []


def test_agents_unknown_id_skipped():
    # id 999 not in index → skipped, not crash
    assert agents_for_proposal(
        "PRUNE", {"proposal": {"target_ids": [999, 1]}}, KIDX) == ["builder"]
