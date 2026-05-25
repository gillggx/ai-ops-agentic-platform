"""Structured JSON logging — copy of python_ai_sidecar/logging_config.py.

Duplicated rather than imported because ontology_simulator ships as an
independent Python package (own venv, own systemd unit). Keep in sync with
the sidecar copy; both implement the schema in docs/logging-schema.md.
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
    JSONFormatter.SERVICE = service
    resolved_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)

    for noisy in ("httpx", "httpcore", "urllib3", "pymongo", "motor"):
        logging.getLogger(noisy).setLevel(
            os.environ.get(f"LOG_LEVEL_{noisy.upper()}", "WARNING")
        )
