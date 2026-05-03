"""Agent eval harness — runs YAML scenarios against the live sidecar,
captures SSE event stream, runs scorers, produces a report.

Usage:
    # Run all suites
    python -m tests.agent_eval.runner

    # Run one suite
    python -m tests.agent_eval.runner --suite builder_intent_7bucket

    # Accept current run as new baseline
    python -m tests.agent_eval.runner --update-baseline

Defaults to prod sidecar via SSH tunnel (set SIDECAR_URL env to override).
Service token from SIDECAR_TOKEN env or arg.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.agent_eval import scorers as S  # noqa: E402


HERE = Path(__file__).parent
SCENARIOS_DIR = HERE / "scenarios"
BASELINE_PATH = HERE / "baseline.json"
REPORT_DIR = HERE / "reports"

DEFAULT_SIDECAR = os.environ.get("SIDECAR_URL", "http://127.0.0.1:8050")
DEFAULT_TOKEN = os.environ.get("SIDECAR_TOKEN", "")
DEFAULT_TIMEOUT_SEC = 45.0


# ── Observed-run dataclass: what we capture from a single case run ────


@dataclass
class ObservedRun:
    """Everything the scorers can look at for one case."""

    case_id: str
    http_status: int
    sse_events: list[dict[str, Any]] = field(default_factory=list)
    elapsed_sec: float = 0.0
    error: str | None = None

    @property
    def event_types(self) -> list[str]:
        return [e["type"] for e in self.sse_events]

    @property
    def event_type_set(self) -> set[str]:
        return set(self.event_types)

    def first_event_data(self, event_type: str) -> dict[str, Any] | None:
        for e in self.sse_events:
            if e["type"] == event_type:
                return e["data"]
        return None

    def all_event_data(self, event_type: str) -> list[dict[str, Any]]:
        return [e["data"] for e in self.sse_events if e["type"] == event_type]


# ── SSE consumer ──────────────────────────────────────────────────────


async def _consume_sse(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any],
    case_id: str,
) -> ObservedRun:
    """Stream SSE response, collect (type, data) frames until done or timeout.

    Uses aiter_lines() — aiter_text() turned out to buffer the entire response
    when the upstream uses chunked transfer + sse_starlette, returning 0
    chunks until the connection closes. aiter_lines() yields per-line.
    """
    obs = ObservedRun(case_id=case_id, http_status=0)
    t0 = time.time()
    try:
        async with client.stream(
            "POST", url,
            headers={**headers, "Accept": "text/event-stream"},
            json=body,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SEC, connect=5.0),
        ) as resp:
            obs.http_status = resp.status_code
            if resp.status_code >= 400:
                body_txt = await resp.aread()
                obs.error = f"HTTP {resp.status_code}: {body_txt[:200]!r}"
                return obs

            event_type = "message"
            data_str = ""
            async for line in resp.aiter_lines():
                if line == "":
                    # Frame boundary — flush.
                    if data_str or event_type != "message":
                        try:
                            data = json.loads(data_str) if data_str else {}
                        except json.JSONDecodeError:
                            data = {"_raw": data_str}
                        obs.sse_events.append({"type": event_type, "data": data})
                        if event_type == "done":
                            return obs
                    event_type = "message"
                    data_str = ""
                elif line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_str = line[5:].strip()
                # else: comment / unknown line — skip
    except httpx.TimeoutException:
        obs.error = "timeout"
    except Exception as e:  # noqa: BLE001
        obs.error = f"{e.__class__.__name__}: {e}"
    finally:
        obs.elapsed_sec = round(time.time() - t0, 2)
    return obs


# ── Case execution ────────────────────────────────────────────────────


async def run_case(
    client: httpx.AsyncClient,
    sidecar_url: str,
    service_token: str,
    case: dict[str, Any],
    suite_endpoint: str,
    suite_default_body: dict[str, Any],
) -> tuple[ObservedRun, list[S.ScoreResult]]:
    """Run one case + score it."""
    headers = {
        "X-Service-Token": service_token,
        "Content-Type": "application/json",
    }
    body = {**suite_default_body, **case.get("input", {})}

    # Endpoint quirks: scenarios always use `message:` for user input, but
    # /internal/agent/build's BuildRequest pydantic schema demands `instruction:`.
    # Translate at the wire so YAML stays readable.
    if suite_endpoint.endswith("/build") and "message" in body and "instruction" not in body:
        body["instruction"] = body.pop("message")

    obs = await _consume_sse(client, f"{sidecar_url}{suite_endpoint}", headers, body, case["id"])

    expect = case.get("expect", {})
    results: list[S.ScoreResult] = []
    for scorer_fn in S.ALL_SCORERS:
        r = scorer_fn(expect, obs)
        if r is None:  # scorer doesn't apply to this case
            continue
        results.append(r)
    return obs, results


# ── Suite + report ────────────────────────────────────────────────────


def load_suite(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f)


async def run_suite(
    suite: dict[str, Any], sidecar_url: str, service_token: str,
) -> dict[str, Any]:
    """Run all cases in a suite. Returns per-case + aggregate scores."""
    endpoint = suite["endpoint"]
    default_body = suite.get("default_body", {})
    cases = suite["cases"]
    case_results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_SEC)) as client:
        for case in cases:
            print(f"  · {case['id']:30s} ", end="", flush=True)
            obs, scores = await run_case(client, sidecar_url, service_token, case, endpoint, default_body)
            passed = all(r.passed for r in scores)
            scores_dict = [{"name": r.name, "passed": r.passed, "msg": r.message} for r in scores]
            case_results.append({
                "id": case["id"],
                "description": case.get("description", ""),
                "input_message": case.get("input", {}).get("message", ""),
                "passed": passed,
                "elapsed_sec": obs.elapsed_sec,
                "http_status": obs.http_status,
                "error": obs.error,
                "event_types": obs.event_types,
                "scores": scores_dict,
            })
            tag = "✓" if passed else "✗"
            print(f"{tag}  {obs.elapsed_sec:5.2f}s  ({sum(1 for r in scores if r.passed)}/{len(scores)} scorers)")
            if not passed:
                for r in scores:
                    if not r.passed:
                        print(f"      {r.name}: {r.message}")

    pass_count = sum(1 for c in case_results if c["passed"])
    return {
        "suite": suite["suite"],
        "endpoint": endpoint,
        "total": len(cases),
        "passed": pass_count,
        "rate": round(pass_count / len(cases), 3) if cases else 0.0,
        "cases": case_results,
    }


def render_report(all_results: list[dict[str, Any]], baseline: dict[str, Any] | None) -> str:
    """Plain text report for terminal + simple HTML side-by-side baseline diff."""
    lines = []
    lines.append("=" * 76)
    lines.append("AGENT EVAL HARNESS — RUN REPORT")
    lines.append(f"Time: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    lines.append("=" * 76)
    grand_total = sum(s["total"] for s in all_results)
    grand_pass = sum(s["passed"] for s in all_results)
    overall_rate = grand_pass / grand_total if grand_total else 0.0
    lines.append(f"OVERALL: {grand_pass}/{grand_total} ({overall_rate:.1%})")
    lines.append("")
    for s in all_results:
        delta = ""
        if baseline:
            base = next((b for b in baseline.get("suites", []) if b["suite"] == s["suite"]), None)
            if base:
                d = s["passed"] - base["passed"]
                delta = f"  (Δ {d:+d} vs baseline {base['passed']}/{base['total']})"
        lines.append(f"  {s['suite']:38s}  {s['passed']:3d}/{s['total']:3d}  {s['rate']:.1%}{delta}")
    lines.append("")
    fails = [
        (s["suite"], c) for s in all_results for c in s["cases"] if not c["passed"]
    ]
    if fails:
        lines.append("FAILED CASES:")
        for suite, c in fails:
            lines.append(f"  ✗ {suite} :: {c['id']}")
            lines.append(f"    msg: {c['input_message']}")
            for sc in c["scores"]:
                if not sc["passed"]:
                    lines.append(f"    [{sc['name']}] {sc['msg']}")
    return "\n".join(lines)


def detect_regressions(all_results: list[dict[str, Any]], baseline: dict[str, Any]) -> list[str]:
    """A regression = case passing in baseline but failing now."""
    regressions = []
    base_cases = {}
    for s in baseline.get("suites", []):
        for c in s["cases"]:
            base_cases[(s["suite"], c["id"])] = c["passed"]
    for s in all_results:
        for c in s["cases"]:
            key = (s["suite"], c["id"])
            if base_cases.get(key) is True and c["passed"] is False:
                regressions.append(f"{s['suite']}::{c['id']}")
    return regressions


# ── CLI ────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent eval harness")
    parser.add_argument("--suite", default="all", help="suite name or 'all'")
    parser.add_argument("--sidecar", default=DEFAULT_SIDECAR, help="sidecar URL")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="X-Service-Token")
    parser.add_argument("--update-baseline", action="store_true",
                        help="overwrite baseline.json with this run's results")
    parser.add_argument("--no-baseline-check", action="store_true",
                        help="don't fail on regressions vs baseline (still prints diff)")
    args = parser.parse_args()

    if not args.token:
        print("ERROR: SIDECAR_TOKEN env or --token required", file=sys.stderr)
        return 2

    suite_files = sorted(SCENARIOS_DIR.glob("*.yaml"))
    if args.suite != "all":
        suite_files = [p for p in suite_files if p.stem == args.suite]
        if not suite_files:
            print(f"ERROR: no suite named '{args.suite}'", file=sys.stderr)
            return 2

    print(f"Sidecar: {args.sidecar}")
    print(f"Suites: {', '.join(p.stem for p in suite_files)}")
    print()

    baseline: dict[str, Any] | None = None
    if BASELINE_PATH.exists():
        with BASELINE_PATH.open() as f:
            baseline = json.load(f)
        print(f"Baseline loaded: {len(baseline.get('suites', []))} suites")
    else:
        print("No baseline yet — first run will establish it (use --update-baseline).")

    all_results: list[dict[str, Any]] = []
    for suite_file in suite_files:
        suite = load_suite(suite_file)
        print(f"\n=== Suite: {suite['suite']} ({len(suite['cases'])} cases) ===")
        result = asyncio.run(run_suite(suite, args.sidecar, args.token))
        all_results.append(result)

    # Render text report
    report_text = render_report(all_results, baseline)
    print()
    print(report_text)

    # Save HTML / JSON report
    REPORT_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    (REPORT_DIR / f"{ts}.json").write_text(
        json.dumps({"timestamp": ts, "suites": all_results}, indent=2, ensure_ascii=False)
    )
    (REPORT_DIR / f"{ts}.txt").write_text(report_text)
    print(f"\nReport saved → reports/{ts}.{{json,txt}}")

    # Baseline update / regression check
    if args.update_baseline:
        BASELINE_PATH.write_text(
            json.dumps({"timestamp": ts, "suites": all_results}, indent=2, ensure_ascii=False)
        )
        print(f"\nBaseline updated → baseline.json")
        return 0

    if baseline and not args.no_baseline_check:
        regressions = detect_regressions(all_results, baseline)
        if regressions:
            print(f"\n❌ REGRESSIONS vs baseline ({len(regressions)} cases):")
            for r in regressions:
                print(f"  - {r}")
            return 1
        else:
            print("\n✅ No regressions vs baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
