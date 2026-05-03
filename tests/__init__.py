"""Test suites for the AIOps platform.

The old DB-fixture machinery (fastapi_backend_service Glass Box tests) was
decommissioned with Phase 8-A-1d (2026-04-25). Active suites:

  tests/agent_eval/      — agent regression harness (LangGraph + Glass Box
                           orchestrator behavioural scoring)

Run from repo root:
    python -m tests.agent_eval.runner
"""
