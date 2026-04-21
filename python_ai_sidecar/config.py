"""Sidecar runtime configuration — loaded once at import time."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SidecarConfig:
    service_token: str
    port: int
    allowed_caller_ips: tuple[str, ...]

    # Phase 5a — reverse direction: sidecar → Java for every DB read/write.
    java_api_url: str
    java_internal_token: str
    java_timeout_sec: float

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
        )


CONFIG = SidecarConfig.from_env()
