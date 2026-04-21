"""Set test env BEFORE any test module imports the sidecar (CONFIG is loaded
at import time, so the env has to be in place first)."""

from __future__ import annotations

import os

os.environ.setdefault("SERVICE_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_CALLERS", "testclient")
os.environ.setdefault("JAVA_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("JAVA_API_URL", "http://fake-java:8002")
