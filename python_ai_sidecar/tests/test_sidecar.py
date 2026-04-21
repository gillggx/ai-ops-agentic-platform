"""Unit tests — run in-process via FastAPI TestClient.

Skip the IP allow-list in tests by calling through TestClient (caller.host == "testclient").
The ALLOWED_CALLERS env var must be set before this module imports; the conftest
fixture handles that.
"""

from __future__ import annotations

import os

os.environ.setdefault("SERVICE_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_CALLERS", "testclient")  # TestClient reports host="testclient"

from fastapi.testclient import TestClient

from python_ai_sidecar.main import app

client = TestClient(app)
HEADERS = {"X-Service-Token": "test-token", "X-User-Id": "42", "X-User-Roles": "IT_ADMIN"}


def test_health_ok():
    res = client.get("/internal/health", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["caller_user_id"] == 42
    assert body["caller_roles"] == ["IT_ADMIN"]


def test_health_rejects_wrong_token():
    res = client.get("/internal/health", headers={"X-Service-Token": "wrong"})
    assert res.status_code == 401


def test_pipeline_execute_round_trips_via_java(monkeypatch):
    """Phase 5a: /execute now fetches pipeline via Java and writes execution_log.
    We stub JavaAPIClient to assert the call pattern without a live Java."""
    from python_ai_sidecar.clients import java_client as jc

    captured = {"get_calls": [], "post_calls": []}

    class StubClient:
        def __init__(self, *a, **k): pass

        async def get_pipeline(self, pipeline_id):
            captured["get_calls"].append(pipeline_id)
            return {"id": pipeline_id, "name": "stub-pipe",
                    "pipelineJson": '{"nodes":[{"id":"a"},{"id":"b"}]}'}

        async def create_execution_log(self, body):
            captured["post_calls"].append(body)
            return {"id": 777, "status": "success"}

    monkeypatch.setattr(jc.JavaAPIClient, "for_caller", classmethod(lambda cls, caller: StubClient()))

    res = client.post(
        "/internal/pipeline/execute",
        headers=HEADERS,
        json={"pipeline_id": 99, "inputs": {"k": "v"}, "triggered_by": "test"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["execution_log_id"] == 777
    assert body["pipeline"]["id"] == 99
    assert body["pipeline"]["name"] == "stub-pipe"
    assert len(body["node_results"]) == 2  # 2 nodes in stub pipelineJson

    # Verify the round-trip made both calls
    assert captured["get_calls"] == [99]
    assert len(captured["post_calls"]) == 1
    assert captured["post_calls"][0]["status"] == "success"
    assert captured["post_calls"][0]["triggeredBy"] == "test"


def test_pipeline_validate_mock():
    res = client.post(
        "/internal/pipeline/validate",
        headers=HEADERS,
        json={"pipeline_json": {"nodes": [{"id": "a"}, {"id": "b"}]}},
    )
    assert res.status_code == 200
    assert res.json()["node_count"] == 2


def test_sandbox_run_mock():
    res = client.post(
        "/internal/sandbox/run",
        headers=HEADERS,
        json={"code": "print('hi')", "inputs": {"a": 1}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["result"]["input_keys"] == ["a"]


def _install_java_stub(monkeypatch):
    """Replace JavaAPIClient.for_caller with an in-memory stub so SSE tests
    don't need a real Java on the wire."""
    from python_ai_sidecar.clients import java_client as jc

    class StubClient:
        def __init__(self): self._memories: list[dict] = []

        async def list_mcps(self, *, mcp_type=None):
            return [{"name": "m_hist", "description": "stub", "mcpType": "system", "inputSchema": "[]"}]

        async def list_skills(self, *, source=None):
            return [{"name": "s_check", "description": "stub", "triggerMode": "both",
                     "source": "skill", "isActive": True}]

        async def list_blocks(self, *, category=None, status=None):
            return [{"name": "load_process_history", "category": "loader", "status": "active"}]

        async def list_agent_memories(self, *, user_id, task_type=None):
            return list(self._memories)

        async def save_agent_memory(self, body):
            body = dict(body)
            body["id"] = len(self._memories) + 1
            self._memories.append(body)
            return body

        async def get_agent_session(self, session_id):
            from python_ai_sidecar.clients.java_client import JavaAPIError
            raise JavaAPIError(404, "not_found", "session not found")

        async def upsert_agent_session(self, session_id, body):
            return {"sessionId": session_id, **body}

    monkeypatch.setattr(jc.JavaAPIClient, "for_caller", classmethod(lambda cls, caller: StubClient()))


def test_agent_sse_streams_both_chat_and_build(monkeypatch):
    """Covers both SSE endpoints in one test — sse-starlette binds asyncio
    primitives at module-init and gets tangled across fresh TestClient event
    loops on Python 3.14, so splitting these into separate tests fails on the
    second run. Single-TestClient run is a safe, stable reproduction of the
    production behaviour."""
    _install_java_stub(monkeypatch)

    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/internal/agent/chat",
            headers=HEADERS,
            json={"message": "hello sidecar", "session_id": "sess-1"},
        ) as res:
            assert res.status_code == 200
            chat_payload = b"".join(chunk for chunk in res.iter_bytes()).decode()
        with c.stream(
            "POST",
            "/internal/agent/build",
            headers=HEADERS,
            json={"instruction": "build me a pipeline"},
        ) as res:
            assert res.status_code == 200
            build_payload = b"".join(chunk for chunk in res.iter_bytes()).decode()

    # Chat graph now emits open → context → recall → message* → memory → checkpoint → done
    assert "event: open" in chat_payload
    assert "event: context" in chat_payload
    assert "event: recall" in chat_payload
    assert "event: message" in chat_payload
    assert "event: memory" in chat_payload
    assert "event: checkpoint" in chat_payload
    assert "event: done" in chat_payload
    assert "sess-1" in chat_payload

    # Build scaffold emits pb_glass_start → pb_glass_chat → pb_glass_op → pb_glass_done
    assert "event: pb_glass_start" in build_payload
    assert "event: pb_glass_chat" in build_payload
    assert "event: pb_glass_op" in build_payload
    assert "event: pb_glass_done" in build_payload
    assert "load_process_history" in build_payload  # from stub block list
