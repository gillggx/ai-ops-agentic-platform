"""MemoryWriter unit tests (spec MULTI_AGENT_MEMORY_SPEC §4 Step 2):
flag gate, deterministic classify tree, caps, fail-open."""
from __future__ import annotations

import asyncio

from python_ai_sidecar.observability.memory_writer import (
    MemoryWriter,
    classify_edit,
    make_memory_writer,
)


def _w() -> MemoryWriter:
    return MemoryWriter(episode_key="ep-t", user_id=7)


def test_flag_gate(monkeypatch):
    import python_ai_sidecar.feature_flags as ff

    monkeypatch.setattr(ff, "is_memory_writes_enabled", lambda: False)
    assert make_memory_writer(episode_key="e", user_id=1) is None
    monkeypatch.setattr(ff, "is_memory_writes_enabled", lambda: True)
    assert isinstance(make_memory_writer(episode_key="e", user_id=1), MemoryWriter)


def test_user_id_defaults_to_1_matching_read_path():
    assert MemoryWriter(episode_key="e", user_id=None).user_id == 1
    assert MemoryWriter(episode_key="e", user_id=42).user_id == 42


def test_classify_edit_deterministic_tree():
    # presentation beats preference when both signals present
    assert classify_edit("畫趨勢", "改成 bar chart 最近 7 天") == "presentation"
    assert classify_edit("最近 24 小時", "最近 12 小時") == "preference"
    assert classify_edit("EQP-01 的資料", "EQP-03 的資料") == "preference"
    assert classify_edit("取得歷史資料", "只取 OOC 事件") == "correction"
    assert classify_edit("", "顯示為表格") == "presentation"


def test_knowledge_cap_and_payload(monkeypatch):
    w = _w()
    calls: list[tuple[str, dict]] = []

    async def _cap(path, body):
        calls.append((path, body))

    monkeypatch.setattr(w, "_post", _cap)
    monkeypatch.setattr(
        "python_ai_sidecar.observability.memory_writer.MAX_KNOWLEDGE_PER_BUILD", 2)

    ok1 = asyncio.run(w.write_knowledge(memo_class="preference", title="t1", body="b",
                                        applies_to="plan", written_by="planner"))
    ok2 = asyncio.run(w.write_knowledge(memo_class="correction", title="t2", body="b"))
    ok3 = asyncio.run(w.write_knowledge(memo_class="domain", title="t3", body="b"))
    assert (ok1, ok2, ok3) == (True, True, False)   # cap=2
    assert len(calls) == 2
    assert calls[0][1]["user_id"] == 7
    assert calls[0][1]["memo_class"] == "preference"
    assert calls[0][1]["applies_to"] == "plan"
    assert calls[0][1]["source"] == "agent_fast"
    assert calls[0][1]["written_by"] == "planner"  # V71 provenance


def test_knowledge_subject_and_status_passthrough(monkeypatch):
    """W2 governance: subject_kind/subject_id/status kwargs ride the POST body."""
    w = _w()
    calls: list[dict] = []

    async def _cap(path, body):
        calls.append(body)

    monkeypatch.setattr(w, "_post", _cap)
    # W3 shape: draft correction linked to a block
    ok = asyncio.run(w.write_knowledge(
        memo_class="correction", title="t", body="b", applies_to="execute",
        active=False, written_by="repair",
        subject_kind="block", subject_id="block_filter", status="draft"))
    assert ok is True
    assert calls[0]["subject_kind"] == "block"
    assert calls[0]["subject_id"] == "block_filter"
    assert calls[0]["status"] == "draft"
    assert calls[0]["active"] is False
    # W1 shape: request_class subject, no id, immediate (no status)
    asyncio.run(w.write_knowledge(memo_class="preference", title="t2", body="b",
                                  subject_kind="request_class"))
    assert calls[1]["subject_kind"] == "request_class"
    assert calls[1]["subject_id"] is None
    assert calls[1]["status"] is None
    # defaults: keys always present (Java-side null-tolerant)
    asyncio.run(w.write_knowledge(memo_class="domain", title="t3", body="b"))
    assert {"subject_kind", "subject_id", "status"} <= set(calls[2])
    assert calls[2]["subject_kind"] is None


def test_doc_memo_cap_and_provenance(monkeypatch):
    w = _w()
    calls: list[dict] = []

    async def _cap(path, body):
        calls.append(body)

    monkeypatch.setattr(w, "_post", _cap)
    monkeypatch.setattr(
        "python_ai_sidecar.observability.memory_writer.MAX_DOC_MEMOS_PER_BUILD", 1)
    ok1 = asyncio.run(w.write_doc_memo(block_id="block_filter", param="value",
                                       memo="m", verdict_context="[]"))
    ok2 = asyncio.run(w.write_doc_memo(block_id="block_sort", param=None,
                                       memo="m2", verdict_context=None))
    assert (ok1, ok2) == (True, False)
    assert calls[0]["from_episode"] == "ep-t"
    assert calls[0]["block_id"] == "block_filter"


def test_failopen_goes_dead(monkeypatch):
    w = _w()

    async def _boom(path, body):
        raise RuntimeError("java down")

    monkeypatch.setattr(w, "_post", _boom)
    assert asyncio.run(w.write_knowledge(memo_class="preference", title="t", body="b")) is False
    assert w._dead is True
    # dead → all subsequent writes silently skipped, never raise
    assert asyncio.run(w.write_doc_memo(block_id="b", param=None, memo="m",
                                        verdict_context=None)) is False


# ── memory_recall capture (Agent Activity Step 1) ──────────────────────


def test_memory_recall_emitted_via_recorder(monkeypatch):
    """build_knowledge_hint records a memory_recall step with recalled rows."""
    import asyncio as _aio
    from python_ai_sidecar.agent_builder.graph_build.nodes import _knowledge_inject as ki
    from python_ai_sidecar.observability.episode_recorder import EpisodeRecorder
    from python_ai_sidecar.observability import set_current_recorder

    rec = EpisodeRecorder(session_id="ep-recall", instruction="i", user_id=1)
    set_current_recorder(rec)

    # fake java: 1 high-priority row; RAG appends via recalled_out
    class _FakeJava:
        async def list_high_priority_knowledge(self, **kw):
            return [{"id": 42, "memo_class": "domain", "title": "SPC=站級", "body": "b"}]

    async def _fake_block(java, *, recalled_out=None, **kw):
        if recalled_out is not None:
            recalled_out.append({"id": 7, "memo_class": "preference",
                                 "title": "預設 12h", "layer": "rag"})
        return "## Retrieved\n  - x"

    monkeypatch.setattr(ki, "JavaAPIClient", lambda *a, **k: _FakeJava(), raising=False)
    # patch the JavaAPIClient import inside the function + the block builder
    import python_ai_sidecar.clients.java_client as jc
    monkeypatch.setattr(jc, "JavaAPIClient", lambda *a, **k: _FakeJava())
    import python_ai_sidecar.agent_orchestrator_v2.nodes.load_context as lc
    monkeypatch.setattr(lc, "_build_knowledge_block", _fake_block)

    out = _aio.run(ki.build_knowledge_hint("查 EQP-01 xbar", user_id=1,
                                           source="goal_plan", agent="planner", round=0))
    assert "SPC=站級" in out
    recall = [s for s in rec._buffer if s["event_type"] == "memory_recall"]
    assert len(recall) == 1
    ids = {r["id"] for r in recall[0]["payload"]["recalled"]}
    assert ids == {42, 7}
    assert recall[0]["agent"] == "planner"
    assert recall[0]["payload"]["round"] == 0
    set_current_recorder(None)
