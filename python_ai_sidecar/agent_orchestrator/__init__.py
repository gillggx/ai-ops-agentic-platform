"""Agent orchestrator — async node graph reaching back to Java for all state.

Design:
  - No LangGraph runtime dependency — a small hand-rolled async graph that's
    easy to reason about and emits SSE-friendly events per node.
  - All state persistence goes through ``JavaAPIClient`` (Java is sole DB owner).
  - LLM calls go through ``llm_stub`` — swap the single file for a real
    OpenAI / Bedrock client behind an env var when keys are provisioned.

Phase 5b proves the pattern. Phase 5c can port richer logic from
``fastapi_backend_service.app.services.agent_orchestrator_v2``.
"""
