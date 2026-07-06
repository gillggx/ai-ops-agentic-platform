#!/usr/bin/env python3
"""Supervisor trace-forensics runner (W3) — offline, PROPOSE-ONLY.

One pass: scan builder traces → aggregate per-block failure / loop hotspots
(F3 gate: single-case hotspots produce nothing) → <= 3 LLM deep-dives →
queue DOC_REVISE / PROMOTE / ISSUE proposals → CFG provider-quality check
(zero LLM) → verify pass for landed proposals. A human reviews everything
in /supervisor.

Usage (on EC2, from /opt/aiops):
    JAVA_INTERNAL_TOKEN=$(grep ^JAVA_INTERNAL_TOKEN= python_ai_sidecar/.env | cut -d= -f2-) \
        venv_sidecar/bin/python -m tools.supervisor_forensics.run

Dry run (print proposals, POST nothing):
    ... -m tools.supervisor_forensics.run --dry-run

Weekly cron (documented, not auto-installed — pair with supervisor_curate):
    30 8 * * 1  cd /opt/aiops && JAVA_INTERNAL_TOKEN=... \
                venv_sidecar/bin/python -m tools.supervisor_forensics.run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _load_sidecar_env() -> None:
    """Load python_ai_sidecar/.env (systemd loads it for the service; a CLI
    run does not, so get_settings() would otherwise see defaults — the first
    prod curation run hit exactly this). Existing env vars win."""
    env = Path(__file__).resolve().parents[2] / "python_ai_sidecar" / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _load_supersede_map(path: str) -> dict:
    """Optional JSON file mapping subject → old proposal id, e.g.
    {"block_union": 12, "DOC_REVISE:block_filter": 15}."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("supersede map must be a JSON object")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as ex:
        print(f"ERROR: cannot read --supersede-map {path}: {ex}", file=sys.stderr)
        raise SystemExit(2)


def main() -> int:
    _load_sidecar_env()

    from python_ai_sidecar.supervisor_forensics.forensics import (
        DEFAULT_DAYS,
        DEFAULT_STATE_FILE,
        DEFAULT_TRACE_DIR,
        MAX_DEEP_DIVES,
        run_forensics,
    )

    ap = argparse.ArgumentParser(
        description="Run one supervisor trace-forensics pass")
    ap.add_argument("--java-base", default=os.environ.get(
        "JAVA_API_URL", "http://localhost:8002").rstrip("/"))
    ap.add_argument("--internal-token",
                    default=os.environ.get("JAVA_INTERNAL_TOKEN", ""),
                    help="X-Internal-Token (default: env JAVA_INTERNAL_TOKEN)")
    ap.add_argument("--trace-dir", default=os.environ.get(
        "BUILDER_TRACE_DIR", DEFAULT_TRACE_DIR))
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"trace mtime selection window (default {DEFAULT_DAYS})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print proposals / verify results instead of POSTing")
    ap.add_argument("--max-deep-dives", type=int, default=MAX_DEEP_DIVES,
                    help=f"LLM deep-dives this run (hard cap {MAX_DEEP_DIVES})")
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE,
                    help="CFG same-day dedupe state (json)")
    ap.add_argument("--supersede-map", default=None,
                    help="optional JSON file mapping subject → old proposal id")
    args = ap.parse_args()

    if not args.internal_token:
        print("ERROR: pass --internal-token or export JAVA_INTERNAL_TOKEN "
              "(see python_ai_sidecar/.env)", file=sys.stderr)
        return 2

    supersede_map = _load_supersede_map(args.supersede_map) \
        if args.supersede_map else None

    res = asyncio.run(run_forensics(
        args.java_base,
        args.internal_token,
        trace_dir=args.trace_dir,
        days=args.days,
        dry_run=args.dry_run,
        max_deep_dives=args.max_deep_dives,
        state_file=args.state_file,
        supersede_map=supersede_map,
    ))
    print(f"traces={res.traces_scanned} failed={res.failed_traces} "
          f"hotspots={res.hotspots} dropped_single_case={res.dropped_single_case} "
          f"deep_dives={res.deep_dives} proposed={res.proposed} "
          f"deduped={res.deduped} skipped_invalid={res.skipped_invalid} "
          f"skipped_gated={res.skipped_gated} cfg={res.cfg_proposed} "
          f"cfg_deduped={res.cfg_deduped} verified={res.verified} "
          f"model={res.llm_model} tokens={res.input_tokens}/{res.output_tokens}"
          f"{' (dry-run)' if args.dry_run else ''}")
    for e in res.errors:
        print(f"  [error] {e}", file=sys.stderr)
    return 0 if not res.errors else 1


if __name__ == "__main__":
    sys.exit(main())
