"""Structured JSON logging for Python services (sidecar + simulator).

Stdout-only — K8s kubelet handles rotation. JSON schema is defined in
``docs/logging-schema.md`` and shared with the Java services so ELK can
ingest the union without per-service parsers.

Usage (at service startup, before any other module logs):

    from python_ai_sidecar.logging_config import configure_logging
    configure_logging("python_ai_sidecar")  # or "ontology_simulator"

The trace_id ContextVar is task-local under asyncio — middleware sets it once
per request and every ``logger.info(...)`` inside that request automatically
picks it up.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

_SENSITIVE_KEY_RE = re.compile(r"(token|api[_-]?key|apikey|password|secret)", re.IGNORECASE)

# Match `key=value`, `key: value`, `"key":"value"` for sensitive keys (in messages).
_SENSITIVE_INLINE_RE = re.compile(
    r"""(?ix)
    (["']?(?:token|api[_-]?key|apikey|password|secret)["']?\s*[=:]\s*["']?)
    ([^\s"',}\]]+)
    """,
)


def _redact_message(s: str) -> str:
    return _SENSITIVE_INLINE_RE.sub(r"\1***", s)


def _redact_context(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {k: ("***" if _SENSITIVE_KEY_RE.search(k) else v) for k, v in ctx.items()}


class JSONFormatter(logging.Formatter):
    """Emits one JSON object per log record. See docs/logging-schema.md."""

    # Set by configure_logging() — bound on the class so we don't pay a closure
    # lookup per record.
    SERVICE: str = "unknown"

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        out: Dict[str, Any] = {
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
            "level": record.levelname,
            "service": self.SERVICE,
            "trace_id": trace_id_ctx.get(),
            "logger": record.name,
            "message": _redact_message(record.getMessage()),
        }
        ctx = getattr(record, "context", None)
        if isinstance(ctx, dict):
            out["context"] = _redact_context(ctx)
        if record.exc_info:
            out["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def configure_logging(service: str, level: str | None = None) -> None:
    """Replace root handlers with a single stdout JSON handler.

    Idempotent: safe to call more than once (re-application produces the same
    handler set). Existing child loggers keep their levels — we only reset
    root handlers + level.
    """
    JSONFormatter.SERVICE = service
    resolved_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)

    # Tame chatty third-party loggers in prod. Override via env if needed.
    for noisy in ("httpx", "httpcore", "openai", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(
            os.environ.get(f"LOG_LEVEL_{noisy.upper()}", "WARNING")
        )
