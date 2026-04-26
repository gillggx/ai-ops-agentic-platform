"""JavaAPIClient — the ONLY way the sidecar touches platform state.

Every DB read / write that the sidecar needs goes through Java's
``/internal/*`` surface. This enforces "Java is the sole DB owner" —
Python never opens a Postgres connection.

Authentication: ``X-Internal-Token`` (plus forwarded user identity so
Java audit log pins the action to the real originating user, not the
sidecar service account).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..auth import CallerContext
from ..config import CONFIG

log = logging.getLogger("python_ai_sidecar.java_client")


# camelCase → snake_case (Java JacksonConfig uses SNAKE_CASE for JSON I/O).
# Sidecar callers write JSON literals in camelCase by convention; we
# normalise on the wire so they don't have to think about it.
def _camel_to_snake(name: str) -> str:
    # Already-snake / all-caps constants pass through unchanged.
    if not any(c.islower() for c in name):
        return name
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _to_snake_keys(obj: Any) -> Any:  # noqa: ANN401
    if isinstance(obj, dict):
        return {_camel_to_snake(k) if isinstance(k, str) else k: _to_snake_keys(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_snake_keys(v) for v in obj]
    return obj


class JavaAPIError(RuntimeError):
    """Raised when Java returns a non-2xx or malformed envelope."""

    def __init__(self, status: int, code: str, message: str, body: Any = None):
        super().__init__(f"Java API {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.body = body


class JavaAPIClient:
    """Thin typed wrapper around httpx.AsyncClient.

    One instance per request is fine — callers typically create with
    ``JavaAPIClient.for_caller(caller)``. Tests override the ``base_url``
    + ``token`` to point at a test fixture server.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_sec: float = 30.0,
        caller: Optional[CallerContext] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_sec = timeout_sec
        self.caller = caller

    @classmethod
    def for_caller(cls, caller: CallerContext) -> "JavaAPIClient":
        return cls(
            CONFIG.java_api_url,
            CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
            caller=caller,
        )

    # ---- raw helpers ----

    def _headers(self) -> dict[str, str]:
        h = {
            "X-Internal-Token": self.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.caller:
            if self.caller.user_id is not None:
                h["X-User-Id"] = str(self.caller.user_id)
            if self.caller.roles:
                h["X-User-Roles"] = ",".join(self.caller.roles)
        return h

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        timeout = httpx.Timeout(self.timeout_sec, connect=5.0)
        # Java JacksonConfig sets PropertyNamingStrategies.SNAKE_CASE so all
        # incoming JSON must use snake_case keys. Sidecar code writes
        # camelCase by convention; convert at the wire.
        if "json" in kwargs and kwargs["json"] is not None:
            kwargs["json"] = _to_snake_keys(kwargs["json"])
        if "params" in kwargs and kwargs["params"] is not None:
            kwargs["params"] = _to_snake_keys(kwargs["params"])
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.request(method, url, headers=self._headers(), **kwargs)
        if res.status_code >= 400:
            try:
                body = res.json()
                err = body.get("error") or {}
                raise JavaAPIError(res.status_code, err.get("code", "unknown"),
                                   err.get("message", res.text), body)
            except ValueError:
                raise JavaAPIError(res.status_code, "http_error", res.text or "(empty)")
        try:
            return res.json()
        except ValueError:
            return {}

    async def _get_data(self, path: str, params: Optional[dict] = None) -> Any:
        env = await self._request("GET", path, params=params)
        return env.get("data") if isinstance(env, dict) else env

    async def _post_data(self, path: str, json: Any) -> Any:
        env = await self._request("POST", path, json=json)
        return env.get("data") if isinstance(env, dict) else env

    async def _patch_data(self, path: str, json: Any) -> Any:
        env = await self._request("PATCH", path, json=json)
        return env.get("data") if isinstance(env, dict) else env

    # ---- typed methods ----

    async def get_pipeline(self, pipeline_id: int) -> dict:
        return await self._get_data(f"/internal/pipelines/{pipeline_id}")

    async def list_pipelines(self, *, status: Optional[str] = None) -> list[dict]:
        params = {"status": status} if status else None
        return await self._get_data("/internal/pipelines", params=params)

    async def get_skill(self, skill_id: int) -> dict:
        return await self._get_data(f"/internal/skills/{skill_id}")

    async def list_skills(self, *, source: Optional[str] = None) -> list[dict]:
        params = {"source": source} if source else None
        return await self._get_data("/internal/skills", params=params)

    async def list_blocks(self, *, category: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
        params: dict[str, str] = {}
        if category:
            params["category"] = category
        if status:
            params["status"] = status
        return await self._get_data("/internal/blocks", params=params or None)

    async def list_mcps(self, *, mcp_type: Optional[str] = None) -> list[dict]:
        params = {"mcpType": mcp_type} if mcp_type else None
        return await self._get_data("/internal/mcp-definitions", params=params)

    async def get_mcp_by_name(self, name: str) -> Optional[dict]:
        """Fetch one MCP definition by name. Returns None if not found.

        Used by sidecar-native ``block_mcp_call`` + ``block_mcp_foreach`` to
        resolve ``mcp_name`` → api_config without a DB session. Java currently
        lacks a by-name endpoint so we list + filter in Python; fine for the
        current catalog size (~20 MCPs).
        """
        all_mcps = await self.list_mcps()
        for m in all_mcps:
            if m.get("name") == name:
                return m
        return None

    async def create_execution_log(self, body: dict) -> dict:
        return await self._post_data("/internal/execution-logs", body)

    async def finish_execution_log(self, log_id: int, body: dict) -> dict:
        return await self._patch_data(f"/internal/execution-logs/{log_id}/finish", body)

    async def save_agent_memory(self, body: dict) -> dict:
        return await self._post_data("/internal/agent-memories", body)

    async def list_agent_memories(self, *, user_id: int, task_type: Optional[str] = None) -> list[dict]:
        params: dict[str, Any] = {"userId": user_id}
        if task_type:
            params["taskType"] = task_type
        return await self._get_data("/internal/agent-memories", params=params)

    async def upsert_agent_session(self, session_id: str, body: dict) -> dict:
        env = await self._request("PUT", f"/internal/agent-sessions/{session_id}", json=body)
        return env.get("data") if isinstance(env, dict) else env

    async def get_agent_session(self, session_id: str) -> dict:
        return await self._get_data(f"/internal/agent-sessions/{session_id}")

    async def create_alarm(self, body: dict) -> dict:
        return await self._post_data("/internal/alarms", body)

    async def create_generated_event(self, body: dict) -> dict:
        return await self._post_data("/internal/generated-events", body)

    # ── Experience memory (Phase 8-A-1d native chat) ──────────────────

    async def search_experience_memory(
        self,
        *,
        user_id: int,
        query_embedding: list[float],
        top_k: int = 5,
        min_similarity: float = 0.6,
        min_confidence: int = 1,
    ) -> list[dict]:
        """pgvector cosine search. Returns list of {memory, similarity}."""
        body = {
            "userId": user_id,
            "queryEmbedding": query_embedding,
            "topK": top_k,
            "minSimilarity": min_similarity,
            "minConfidence": min_confidence,
        }
        data = await self._post_data("/internal/agent-experience-memories/search", body)
        return data or []

    async def write_experience_memory(
        self,
        *,
        user_id: int,
        intent_summary: str,
        abstract_action: str,
        embedding: Optional[list[float]] = None,
        source: str = "auto",
        source_session_id: Optional[str] = None,
        confidence_score: Optional[int] = None,
        dedup_threshold: Optional[float] = 0.92,
    ) -> dict:
        """Insert (or bump dedup) experience memory. Returns {memory, dedupHit, similarity}."""
        body: dict[str, Any] = {
            "userId": user_id,
            "intentSummary": intent_summary,
            "abstractAction": abstract_action,
            "source": source,
        }
        if embedding is not None:
            body["embedding"] = embedding
        if source_session_id is not None:
            body["sourceSessionId"] = source_session_id
        if confidence_score is not None:
            body["confidenceScore"] = confidence_score
        if dedup_threshold is not None:
            body["dedupThreshold"] = dedup_threshold
        return await self._post_data("/internal/agent-experience-memories", body)

    async def feedback_experience_memory(self, memory_id: int, outcome: str) -> dict:
        env = await self._request(
            "PUT",
            f"/internal/agent-experience-memories/{memory_id}/feedback",
            json={"outcome": outcome},
        )
        return env.get("data") if isinstance(env, dict) else env

    async def list_experience_memories(
        self, *, user_id: int, status: str = "ACTIVE",
    ) -> list[dict]:
        params = {"userId": user_id, "status": status}
        return await self._get_data("/internal/agent-experience-memories", params=params)

    # ── User preference + system parameter ────────────────────────────

    async def get_user_preference(self, user_id: int) -> dict:
        """Returns {id, userId, preferences, soulOverride}. Empty fields when absent."""
        return await self._get_data(f"/internal/user-preferences/{user_id}")

    async def get_system_parameter(self, key: str) -> dict:
        """Returns {id, key, value, description}. Empty fields when absent."""
        return await self._get_data(f"/internal/system-parameters/{key}")
