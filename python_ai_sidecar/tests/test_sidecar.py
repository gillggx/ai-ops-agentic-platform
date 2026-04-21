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


def test_pipeline_execute_mock():
    res = client.post(
        "/internal/pipeline/execute",
        headers=HEADERS,
        json={"pipeline_id": 99, "pipeline_json": {"nodes": [{"id": "a"}]}, "inputs": {"k": "v"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["status"] == "mock_success"
    assert body["mock_output"]["echo"]["pipeline_id"] == 99
    assert body["mock_output"]["echo"]["inputs_count"] == 1


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


def test_agent_sse_streams_both_chat_and_build():
    """Covers both SSE endpoints in one test — sse-starlette binds asyncio
    primitives at module-init and gets tangled across fresh TestClient event
    loops on Python 3.14, so splitting these into separate tests fails on the
    second run. Single-TestClient run is a safe, stable reproduction of the
    production behaviour."""
    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/internal/agent/chat",
            headers=HEADERS,
            json={"message": "hello", "session_id": "sess-1"},
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

    assert "event: open" in chat_payload
    assert "event: message" in chat_payload
    assert "event: done" in chat_payload
    assert "sess-1" in chat_payload

    assert "event: pb_glass_start" in build_payload
    assert "event: pb_glass_chat" in build_payload
    assert "event: pb_glass_op" in build_payload
    assert "event: pb_glass_done" in build_payload
