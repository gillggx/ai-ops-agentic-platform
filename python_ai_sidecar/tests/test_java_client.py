"""Unit tests for JavaAPIClient — uses httpx MockTransport, no real Java needed."""

from __future__ import annotations

import os

os.environ.setdefault("JAVA_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("JAVA_API_URL", "http://fake-java:8002")

import httpx
import pytest

from python_ai_sidecar.auth import CallerContext
from python_ai_sidecar.clients.java_client import JavaAPIClient, JavaAPIError


def _handler(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode() if request.content else "",
        })
        if request.url.path == "/internal/pipelines/42":
            return httpx.Response(200, json={
                "ok": True,
                "data": {"id": 42, "name": "test-pipe", "status": "active",
                         "pipelineJson": '{"nodes":[{"id":"a"}]}'},
            })
        if request.url.path == "/internal/execution-logs" and request.method == "POST":
            return httpx.Response(200, json={"ok": True, "data": {"id": 501, "status": "success"}})
        if request.url.path == "/internal/skills/99":
            return httpx.Response(404, json={
                "ok": False, "error": {"code": "not_found", "message": "skill not found"},
            })
        return httpx.Response(500, json={"ok": False, "error": {"code": "oops", "message": "unexpected"}})
    return handler


@pytest.mark.asyncio
async def test_client_forwards_token_and_caller_headers():
    captured: list = []
    transport = httpx.MockTransport(_handler(captured))
    caller = CallerContext(user_id=7, roles=("PE",))
    client = JavaAPIClient("http://fake-java:8002", "test-internal-token", caller=caller)

    # Monkeypatch _request to reuse our transport-backed client
    async def _request(method, path, **kwargs):
        async with httpx.AsyncClient(transport=transport) as c:
            res = await c.request(method, f"http://fake-java:8002{path}",
                                  headers=client._headers(), **kwargs)
        if res.status_code >= 400:
            body = res.json() if res.content else {}
            err = body.get("error") or {}
            raise JavaAPIError(res.status_code, err.get("code", "unknown"),
                               err.get("message", res.text), body)
        return res.json() if res.content else {}
    client._request = _request  # type: ignore

    # 1. Successful GET round-trip
    pipe = await client.get_pipeline(42)
    assert pipe["id"] == 42
    assert pipe["name"] == "test-pipe"

    # Verify headers were forwarded
    assert captured[0]["headers"]["x-internal-token"] == "test-internal-token"
    assert captured[0]["headers"]["x-user-id"] == "7"
    assert captured[0]["headers"]["x-user-roles"] == "PE"

    # 2. 404 raises JavaAPIError
    with pytest.raises(JavaAPIError) as exc:
        await client.get_skill(99)
    assert exc.value.status == 404
    assert exc.value.code == "not_found"

    # 3. POST round-trip
    result = await client.create_execution_log({"triggeredBy": "test", "status": "success"})
    assert result["id"] == 501

    # Verify POST body was sent
    post_capture = [c for c in captured if c["method"] == "POST"][0]
    assert '"triggeredBy"' in post_capture["content"]


def test_headers_without_caller():
    client = JavaAPIClient("http://fake-java:8002", "tok", caller=None)
    h = client._headers()
    assert h["X-Internal-Token"] == "tok"
    assert "X-User-Id" not in h
    assert "X-User-Roles" not in h
