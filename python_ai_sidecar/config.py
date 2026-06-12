"""Sidecar runtime configuration — loaded once at import time."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class SidecarConfig:
    service_token: str
    port: int
    allowed_caller_ips: tuple[str, ...]

    # Phase 5a — reverse direction: sidecar → Java for every DB read/write.
    java_api_url: str
    java_internal_token: str
    java_timeout_sec: float

    # Performance feature flags (2026-06-11 / 2026-06-12).
    # Read once at startup; per-request override via `X-Feature-Flags` HTTP header
    # (see python_ai_sidecar/feature_flags.py).
    enable_prompt_cache: bool
    enable_auto_signal: bool
    # Round 1 (2026-06-12): three flags for speed/accuracy improvements.
    enable_atomic_add_connect: bool
    enable_auto_verifier: bool
    enable_strict_tool_id: bool
    # Round 2 (2026-06-12): orphan-duplicate add_node guard. Rejects when canvas
    # already has a node with the same (block_id, params) AND no downstream
    # edges — KIMI's "echo" behaviour signature. See SLASH-13 R2 trace analysis.
    enable_no_duplicate_node: bool
    # Round 3 (2026-06-12): context-aware per-sub-phase prompt assembly. Mid-phase
    # canvas snapshot gains upstream output columns + sample so construct/tune
    # rounds can fill params without blind-guessing. See
    # docs/agent-subphase-prompt-design.html.
    enable_rich_canvas_snapshot: bool

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        token = os.getenv("SERVICE_TOKEN", "").strip()
        if not token:
            # Dev fallback — production MUST set SERVICE_TOKEN via env.
            token = "dev-service-token"
        java_token = os.getenv("JAVA_INTERNAL_TOKEN", "").strip() or "dev-internal-token"

        return cls(
            service_token=token,
            port=int(os.getenv("SIDECAR_PORT", "8050")),
            allowed_caller_ips=tuple(
                ip.strip() for ip in os.getenv("ALLOWED_CALLERS", "127.0.0.1,::1").split(",") if ip.strip()
            ),
            java_api_url=os.getenv("JAVA_API_URL", "http://localhost:8002").rstrip("/"),
            java_internal_token=java_token,
            java_timeout_sec=float(os.getenv("JAVA_TIMEOUT_SEC", "30")),
            enable_prompt_cache=_read_bool_env("ENABLE_PROMPT_CACHE", default=True),
            enable_auto_signal=_read_bool_env("ENABLE_AUTO_SIGNAL", default=False),
            enable_atomic_add_connect=_read_bool_env("ENABLE_ATOMIC_ADD_CONNECT", default=False),
            enable_auto_verifier=_read_bool_env("ENABLE_AUTO_VERIFIER", default=False),
            enable_strict_tool_id=_read_bool_env("ENABLE_STRICT_TOOL_ID", default=False),
            enable_no_duplicate_node=_read_bool_env("ENABLE_NO_DUPLICATE_NODE", default=False),
            enable_rich_canvas_snapshot=_read_bool_env("ENABLE_RICH_CANVAS_SNAPSHOT", default=False),
        )


CONFIG = SidecarConfig.from_env()
