#!/usr/bin/env python3
"""Phase 8-B Parity Probe.

Runs the same pipeline_json + inputs against:
  - old Python fastapi-backend :8001 (source of truth)
  - new sidecar :8050 native executor

and diffs the response to flag regressions before we flip any routing.

Usage (on EC2 or locally):

    python3 scripts/phase8b_parity_probe.py \\
        --old http://localhost:8001 \\
        --new http://localhost:8050 \\
        --old-token "$INTERNAL_API_TOKEN" \\
        --new-token "$SERVICE_TOKEN" \\
        --pipeline fixtures/pb_pipeline_13.json

Each fixture is a dict with ``{pipeline_json: {...}, inputs: {...}}``.
If ``--pipeline`` is a directory, every .json file inside is probed and
a summary table is printed.

Exit codes:
  0 — all fixtures parity-identical (ignoring timestamp / run_id fields)
  1 — at least one fixture differs
  2 — at least one backend unreachable
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


# Fields we expect to differ even on perfect parity and mask out before diff.
_IGNORED_FIELDS = frozenset({
    "duration_ms",
    "started_at",
    "finished_at",
    "execution_log_id",
    "run_id",
    "caller_user_id",
    "source",  # "native" vs "python_fallback"
    "_native_error",
})


@dataclass
class ProbeResult:
    fixture: str
    old_status: str
    new_status: str
    identical: bool
    diff_summary: str


def _strip_ignored(obj: Any) -> Any:
    """Recursively drop _IGNORED_FIELDS keys for clean diff."""
    if isinstance(obj, dict):
        return {k: _strip_ignored(v) for k, v in obj.items() if k not in _IGNORED_FIELDS}
    if isinstance(obj, list):
        return [_strip_ignored(v) for v in obj]
    return obj


def _diff_summary(old: dict, new: dict) -> str:
    """Compact one-line summary of where the two responses differ.
    Full JSON diff is omitted — call sites should inspect manually.
    """
    o = _strip_ignored(old)
    n = _strip_ignored(new)
    if o == n:
        return "identical (after masking ignored fields)"
    o_keys = set(o.keys()) if isinstance(o, dict) else set()
    n_keys = set(n.keys()) if isinstance(n, dict) else set()
    only_old = o_keys - n_keys
    only_new = n_keys - o_keys
    common_diff = [k for k in (o_keys & n_keys) if o.get(k) != n.get(k)]
    parts = []
    if only_old: parts.append(f"only_old={sorted(only_old)}")
    if only_new: parts.append(f"only_new={sorted(only_new)}")
    if common_diff: parts.append(f"diff_keys={sorted(common_diff)}")
    return "; ".join(parts) or "deep-diff (top-level keys equal, nested differs)"


async def _post(url: str, token: str, body: dict, header_key: str) -> dict | None:
    """POST JSON with auth. Returns parsed JSON or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                url,
                json=body,
                headers={header_key: f"Bearer {token}"} if header_key == "Authorization"
                        else {header_key: token},
            )
            if res.status_code >= 400:
                return {"__http_error__": res.status_code, "body": res.text[:500]}
            return res.json()
    except Exception as ex:  # noqa: BLE001
        return {"__transport_error__": str(ex)[:200]}


async def probe_fixture(
    fixture_path: Path,
    old_base: str, new_base: str,
    old_token: str, new_token: str,
) -> ProbeResult:
    fixture = json.loads(fixture_path.read_text())
    # triggered_by must be one of the enum: user|agent|schedule|event
    body = {
        "pipeline_json": fixture.get("pipeline_json") or fixture,
        "inputs": fixture.get("inputs") or {},
        "triggered_by": fixture.get("triggered_by") or "user",
    }

    # Old Python backend uses /api/v1/pipeline-builder/execute with Bearer token.
    old_resp = await _post(
        f"{old_base}/api/v1/pipeline-builder/execute",
        old_token,
        body,
        header_key="Authorization",
    )
    # New sidecar uses /internal/pipeline/execute with X-Service-Token.
    new_resp = await _post(
        f"{new_base}/internal/pipeline/execute",
        new_token,
        body,
        header_key="X-Service-Token",
    )

    old_status = _extract_status(old_resp)
    new_status = _extract_status(new_resp)
    identical = _strip_ignored(old_resp) == _strip_ignored(new_resp)
    diff = _diff_summary(old_resp or {}, new_resp or {})

    return ProbeResult(
        fixture=fixture_path.name,
        old_status=old_status,
        new_status=new_status,
        identical=identical,
        diff_summary=diff,
    )


def _extract_status(resp: dict | None) -> str:
    if resp is None: return "NO_RESPONSE"
    if "__http_error__" in resp: return f"HTTP_{resp['__http_error__']}"
    if "__transport_error__" in resp: return "TRANSPORT_ERR"
    return str(resp.get("status") or resp.get("ok") or "?")[:20]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", default="http://localhost:8001", help="Old Python backend base URL")
    parser.add_argument("--new", default="http://localhost:8050", help="New sidecar base URL")
    parser.add_argument("--old-token", required=True, help="Bearer token for old (INTERNAL_API_TOKEN)")
    parser.add_argument("--new-token", required=True, help="Service token for sidecar (SERVICE_TOKEN)")
    parser.add_argument(
        "--pipeline", required=True,
        help="Path to a fixture .json OR a directory of fixtures",
    )
    args = parser.parse_args()

    path = Path(args.pipeline)
    if path.is_file():
        fixtures = [path]
    elif path.is_dir():
        fixtures = sorted(path.glob("*.json"))
        if not fixtures:
            print(f"no .json fixtures in {path}", file=sys.stderr)
            return 2
    else:
        print(f"fixture path not found: {path}", file=sys.stderr)
        return 2

    results: list[ProbeResult] = []
    for fx in fixtures:
        r = await probe_fixture(fx, args.old, args.new, args.old_token, args.new_token)
        results.append(r)
        mark = "✅" if r.identical else "❌"
        print(f"{mark}  {r.fixture:<40}  old={r.old_status:<12}  new={r.new_status:<12}  {r.diff_summary}")

    all_identical = all(r.identical for r in results)
    any_transport_err = any("TRANSPORT_ERR" in r.old_status or "TRANSPORT_ERR" in r.new_status for r in results)

    print()
    print(f"Summary: {sum(r.identical for r in results)}/{len(results)} identical")
    if any_transport_err:
        return 2
    return 0 if all_identical else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
