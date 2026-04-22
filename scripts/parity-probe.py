"""Parity probe — diff Python (:8001) vs Java (:8002) for Frontend-used routes.

Runs the same URL against both backends using each's auth model and classifies
the result: identical / envelope-diff / path-diff / auth-diff / server-error.

Usage on EC2:
    python3 /opt/aiops/scripts/parity-probe.py > /tmp/parity-probe.md

Needs these env vars:
    PY_TOKEN   shared-secret token the old Python FastAPI accepts
               (from aiops-app/.env.local.pre-java-cutover INTERNAL_API_TOKEN)
    JAVA_URL   http://localhost:8002       (default)
    PY_URL     http://localhost:8001       (default)
    ADMIN_USER admin                       (default — logged in to Java for JWT)
    ADMIN_PASS admin                       (default)

Only GET endpoints are probed (no state mutation). Critical mutations are
smoke-tested manually in P2-6.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass


PY_URL = os.getenv("PY_URL", "http://localhost:8001").rstrip("/")
JAVA_URL = os.getenv("JAVA_URL", "http://localhost:8002").rstrip("/")
PY_TOKEN = os.getenv("PY_TOKEN", "").strip()
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")


# (frontend-visible name, HTTP method, path template)
# Path params use real ids that exist in prod (1 for most entities — adjust if
# needed; these are probe-safe because we only do GET).
ROUTES: list[tuple[str, str, str]] = [
    # --- Alarm Center ---
    ("admin/alarms", "GET", "/api/v1/alarms"),
    ("admin/alarms?status=active", "GET", "/api/v1/alarms?status=active"),
    ("admin/alarms/stats", "GET", "/api/v1/alarms/stats"),

    # --- Event types ---
    ("admin/event-types", "GET", "/api/v1/event-types"),
    ("admin/event-types/6/log", "GET", "/api/v1/event-types/6/log?limit=5"),

    # --- Skills ---
    ("admin/skills", "GET", "/api/v1/skills"),
    ("admin/skills/3", "GET", "/api/v1/skills/3"),
    ("admin/my-skills", "GET", "/api/v1/my-skills"),

    # --- Rules (diagnostic rules) ---
    ("admin/rules", "GET", "/api/v1/diagnostic-rules"),

    # --- Auto-patrols ---
    ("admin/auto-patrols", "GET", "/api/v1/auto-patrols?active_only=false&with_stats=false"),
    ("admin/auto-patrols/1", "GET", "/api/v1/auto-patrols/1"),
    ("admin/auto-patrols/1/executions", "GET", "/api/v1/auto-patrols/1/executions?limit=10"),

    # --- MCPs ---
    ("admin/mcps", "GET", "/api/v1/mcp-definitions"),
    ("mcp-catalog", "GET", "/api/v1/mcp-definitions/catalog"),

    # --- Pipeline Builder ---
    ("pipeline-builder/pipelines", "GET", "/api/v1/pipeline-builder/pipelines"),
    ("pipeline-builder/pipelines/1", "GET", "/api/v1/pipeline-builder/pipelines/1"),
    ("pipeline-builder/blocks", "GET", "/api/v1/pipeline-builder/blocks"),
    ("pipeline-builder/published-skills", "GET", "/api/v1/pipeline-builder/published-skills"),
    ("pipeline-builder/auto-check-rules", "GET", "/api/v1/pipeline-builder/auto-check-rules"),

    # --- Memories / admin ---
    ("admin/memories", "GET", "/api/v1/agent-memories?userId=1"),
    ("admin/briefing", "GET", "/api/v1/briefing"),
    ("admin/monitor", "GET", "/api/v1/system/monitor"),

    # --- Agent session ---
    ("agent/session", "GET", "/api/v1/agent/sessions"),
]


def _get(base: str, path: str, auth_header: str) -> tuple[int, str, object]:
    """Returns (status, raw_body, parsed_json_or_None)."""
    url = base + path
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            parsed = None
            try:
                parsed = json.loads(body)
            except Exception:
                pass
            return r.status, body, parsed
    except urllib.error.HTTPError as e:
        body = (e.read().decode("utf-8", errors="replace") if e.fp else "") or ""
        try:
            parsed = json.loads(body) if body else None
        except Exception:
            parsed = None
        return e.code, body, parsed
    except Exception as e:
        return -1, f"network error: {e}", None


def _describe_shape(obj: object, depth: int = 2) -> str:
    """Tiny shape summariser — list/dict depth + keys/length."""
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, (int, float)):
        return f"{type(obj).__name__}"
    if isinstance(obj, str):
        return f"str({len(obj)})"
    if isinstance(obj, list):
        if not obj:
            return "list[0]"
        if depth <= 0:
            return f"list[{len(obj)}]"
        first = _describe_shape(obj[0], depth - 1)
        return f"list[{len(obj)} of {first}]"
    if isinstance(obj, dict):
        keys = sorted(obj.keys())[:6]
        if depth <= 0:
            return f"dict({len(obj)} keys)"
        inner = ", ".join(f"{k}:{_describe_shape(obj[k], depth - 1)}" for k in keys)
        more = "..." if len(obj) > 6 else ""
        return f"dict{{{inner}{more}}}"
    return type(obj).__name__


def _classify(py_status: int, java_status: int, py_obj: object, java_obj: object) -> str:
    if py_status == -1 or java_status == -1:
        return "network"
    if py_status == 401 or java_status == 401:
        return "auth-diff"
    if py_status == 404 and java_status != 404:
        return "path-diff-py"
    if java_status == 404 and py_status != 404:
        return "path-diff-java"
    if py_status >= 500 or java_status >= 500:
        return "server-error"
    if py_status != java_status:
        return "status-diff"
    # Both 2xx — compare shapes
    py_shape = _describe_shape(py_obj)
    java_shape = _describe_shape(java_obj)
    if py_shape == java_shape:
        return "identical"
    return "envelope-diff"


@dataclass
class Row:
    name: str
    method: str
    path: str
    py_status: int
    java_status: int
    py_shape: str
    java_shape: str
    classification: str


def login_java() -> str:
    """Returns a Bearer JWT from Java's /api/v1/auth/login."""
    req = urllib.request.Request(
        JAVA_URL + "/api/v1/auth/login",
        data=json.dumps({"username": ADMIN_USER, "password": ADMIN_PASS}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read().decode())
    return body["data"]["access_token"]


def main() -> int:
    if not PY_TOKEN:
        print("ERROR: set PY_TOKEN env (Frontend's old shared-secret token)", file=sys.stderr)
        return 1
    java_jwt = login_java()

    py_auth = f"Bearer {PY_TOKEN}"
    java_auth = f"Bearer {java_jwt}"

    rows: list[Row] = []
    for name, method, path in ROUTES:
        py_status, _, py_obj = _get(PY_URL, path, py_auth)
        java_status, _, java_obj = _get(JAVA_URL, path, java_auth)
        py_shape = _describe_shape(py_obj)
        java_shape = _describe_shape(java_obj)
        cls = _classify(py_status, java_status, py_obj, java_obj)
        rows.append(Row(name, method, path, py_status, java_status, py_shape, java_shape, cls))

    # --- Report (markdown) ---
    buckets: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        buckets[r.classification].append(r)

    print("# Parity probe report")
    print()
    print(f"- Python upstream: `{PY_URL}`")
    print(f"- Java upstream:   `{JAVA_URL}`")
    print(f"- Routes tested:   {len(rows)}")
    print(f"- Identical:       {len(buckets.get('identical', []))}")
    print(f"- Envelope diffs:  {len(buckets.get('envelope-diff', []))}")
    print(f"- Path diffs py:   {len(buckets.get('path-diff-py', []))}")
    print(f"- Path diffs java: {len(buckets.get('path-diff-java', []))}")
    print(f"- Status diffs:    {len(buckets.get('status-diff', []))}")
    print(f"- Server errors:   {len(buckets.get('server-error', []))}")
    print(f"- Auth diffs:      {len(buckets.get('auth-diff', []))}")
    print()

    order = ["server-error", "path-diff-java", "status-diff", "envelope-diff",
             "path-diff-py", "auth-diff", "network", "identical"]
    for cls in order:
        group = buckets.get(cls, [])
        if not group:
            continue
        print(f"## {cls} ({len(group)})")
        print()
        print("| Route | Method | Path | py | java | py_shape | java_shape |")
        print("|---|---|---|---|---|---|---|")
        for r in group:
            py_shape_trunc = r.py_shape[:60] + ("…" if len(r.py_shape) > 60 else "")
            java_shape_trunc = r.java_shape[:60] + ("…" if len(r.java_shape) > 60 else "")
            print(f"| `{r.name}` | {r.method} | `{r.path[:70]}` | {r.py_status} | {r.java_status} | `{py_shape_trunc}` | `{java_shape_trunc}` |")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
