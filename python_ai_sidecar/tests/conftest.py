"""Set test env BEFORE any test module imports the sidecar (CONFIG is loaded
at import time, so the env has to be in place first)."""

from __future__ import annotations

import importlib
import os

import pytest

os.environ.setdefault("SERVICE_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_CALLERS", "testclient")
os.environ.setdefault("JAVA_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("JAVA_API_URL", "http://fake-java:8002")


@pytest.fixture(autouse=True)
def _reset_feature_flag_config():
    """Reset the CONFIG + feature_flags singletons after every test.

    Several feature-flag tests do ``monkeypatch.setenv(...) + importlib.reload``
    to exercise a non-default flag value. monkeypatch restores the env var on
    teardown, but the *reloaded module* keeps the test-time CONFIG — which then
    leaks into unrelated tests (e.g. a leaked ENABLE_NO_DUPLICATE_NODE=1 trips
    the duplicate guard in atomic-add-connect tests). Reload both modules from
    the (restored) environment after each test so every test starts clean.
    """
    yield
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
