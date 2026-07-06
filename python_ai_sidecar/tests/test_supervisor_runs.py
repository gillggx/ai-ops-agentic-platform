"""Manual supervisor-run endpoint tests — no network, no LLM.

Covers: start + single-flight 409, status shape before / during (simulated
long run) / after, both run kinds routed to the right run fn with CONFIG
credentials, max_deep_dives request-level cap, run-task failure recorded in
`last` (ok=false) instead of raising, and auth gating.

The detached run task lives on the request's event loop, so these tests use
``with TestClient(...)`` (one persistent portal loop for all requests) on a
mini app carrying just the supervisor_runs router — the main app's lifespan
would start the background pollers. Registration on the real app is asserted
separately via its route table.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from python_ai_sidecar.routers import supervisor_runs
from python_ai_sidecar.supervisor_curation.proposer import CurationRunResult
from python_ai_sidecar.supervisor_forensics.forensics import ForensicsRunResult

HEADERS = {"X-Service-Token": "test-token"}
RUNS_URL = "/internal/supervisor/runs"
STATUS_URL = "/internal/supervisor/runs/status"

_mini_app = FastAPI()
_mini_app.include_router(supervisor_runs.router)


@pytest.fixture()
def client():
    supervisor_runs._reset_state_for_tests()
    with TestClient(_mini_app) as c:
        yield c
    supervisor_runs._reset_state_for_tests()


def _wait_until_idle(client: TestClient, timeout: float = 5.0) -> dict:
    """Poll status until the detached task finishes; return the final body."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(STATUS_URL, headers=HEADERS).json()
        if not body["running"]:
            return body
        time.sleep(0.02)
    pytest.fail("supervisor run did not finish within timeout")


# ── registration + auth + validation ─────────────────────────────────────

def test_router_registered_on_main_app():
    from python_ai_sidecar.main import app
    paths = {r.path for r in app.routes}
    assert RUNS_URL in paths
    assert STATUS_URL in paths


def test_endpoints_require_service_token(client):
    assert client.get(STATUS_URL,
                      headers={"X-Service-Token": "wrong"}).status_code == 401
    assert client.post(RUNS_URL, headers={"X-Service-Token": "wrong"},
                       json={"kind": "forensics"}).status_code == 401


def test_unknown_kind_rejected(client):
    res = client.post(RUNS_URL, headers=HEADERS, json={"kind": "vibes"})
    assert res.status_code == 422


def test_status_initial_shape(client):
    body = client.get(STATUS_URL, headers=HEADERS).json()
    assert body == {"running": False, "kind": None,
                    "started_at": None, "last": None}


# ── start + single-flight + during/after status ──────────────────────────

def test_single_flight_409_and_status_lifecycle(client, monkeypatch):
    release = threading.Event()
    seen = {}

    async def fake_forensics(java_base, internal_token, **kw):
        seen["args"] = (java_base, internal_token, kw)
        import asyncio
        while not release.is_set():          # cross-thread gate, loop-safe poll
            await asyncio.sleep(0.01)
        return ForensicsRunResult(traces_scanned=4, hotspots=1, proposed=1)

    monkeypatch.setattr(supervisor_runs, "run_forensics", fake_forensics)

    try:
        res = client.post(RUNS_URL, headers=HEADERS,
                          json={"kind": "forensics", "days": 3})
        assert res.status_code == 200
        first = res.json()
        assert first["started"] is True and first["run_id"]

        # during: status reflects the active run
        during = client.get(STATUS_URL, headers=HEADERS).json()
        assert during["running"] is True
        assert during["kind"] == "forensics"
        assert during["started_at"]
        assert during["last"] is None

        # single-flight: second POST (any kind) → 409 with the active run info
        dup = client.post(RUNS_URL, headers=HEADERS, json={"kind": "curation"})
        assert dup.status_code == 409
        assert dup.json() == {"running": True, "kind": "forensics",
                              "started_at": during["started_at"]}
    finally:
        release.set()

    after = _wait_until_idle(client)
    assert after["running"] is False and after["kind"] is None
    last = after["last"]
    assert last["run_id"] == first["run_id"]
    assert last["kind"] == "forensics"
    assert last["started_at"] == during["started_at"]
    assert last["finished_at"]
    assert last["ok"] is True
    assert last["summary"].startswith("traces=4 ")
    assert "proposed=1" in last["summary"]

    # credentials from CONFIG (conftest env), never from the body
    java_base, token, kw = seen["args"]
    assert java_base == "http://fake-java:8002"
    assert token == "test-internal-token"
    assert kw["days"] == 3

    # a new run is accepted once the previous one finished
    res2 = client.post(RUNS_URL, headers=HEADERS, json={"kind": "forensics"})
    assert res2.status_code == 200
    _wait_until_idle(client)


def test_max_deep_dives_capped_at_ten(client, monkeypatch):
    captured = {}

    async def fake_forensics(java_base, internal_token, **kw):
        captured.update(kw)
        return ForensicsRunResult()

    monkeypatch.setattr(supervisor_runs, "run_forensics", fake_forensics)
    res = client.post(RUNS_URL, headers=HEADERS,
                      json={"kind": "forensics", "max_deep_dives": 99})
    assert res.status_code == 200
    _wait_until_idle(client)
    assert captured["max_deep_dives"] == supervisor_runs.REQUEST_MAX_DEEP_DIVES


def test_curation_run_routes_and_summarizes(client, monkeypatch):
    async def fake_curation(java_base, internal_token):
        assert java_base == "http://fake-java:8002"
        assert internal_token == "test-internal-token"
        return CurationRunResult(proposed=2, deduped=1, llm_model="stub",
                                 input_tokens=10, output_tokens=5)

    monkeypatch.setattr(supervisor_runs, "run_curation", fake_curation)
    res = client.post(RUNS_URL, headers=HEADERS, json={"kind": "curation"})
    assert res.status_code == 200
    last = _wait_until_idle(client)["last"]
    assert last["kind"] == "curation" and last["ok"] is True
    assert last["summary"] == ("proposed=2 skipped_invalid=0 deduped=1 "
                               "errors=0 model=stub tokens=10/5")


# ── failure paths: recorded, never raised ─────────────────────────────────

def test_run_exception_recorded_not_raised(client, monkeypatch):
    async def boom(java_base, internal_token, **kw):
        raise RuntimeError("java is down")

    monkeypatch.setattr(supervisor_runs, "run_forensics", boom)
    res = client.post(RUNS_URL, headers=HEADERS, json={"kind": "forensics"})
    assert res.status_code == 200                 # start always succeeds
    after = _wait_until_idle(client)
    assert after["running"] is False              # slot freed for the next run
    last = after["last"]
    assert last["ok"] is False
    assert last["summary"] == "RuntimeError: java is down"

    # the failed run must not wedge single-flight
    res2 = client.post(RUNS_URL, headers=HEADERS, json={"kind": "forensics"})
    assert res2.status_code == 200
    assert _wait_until_idle(client)["last"]["ok"] is False


def test_run_result_errors_marks_not_ok(client, monkeypatch):
    async def fake_forensics(java_base, internal_token, **kw):
        return ForensicsRunResult(traces_scanned=1,
                                  errors=["DOC_REVISE: proposals POST HTTP 500"])

    monkeypatch.setattr(supervisor_runs, "run_forensics", fake_forensics)
    client.post(RUNS_URL, headers=HEADERS, json={"kind": "forensics"})
    last = _wait_until_idle(client)["last"]
    assert last["ok"] is False
    assert "errors: DOC_REVISE: proposals POST HTTP 500" in last["summary"]
