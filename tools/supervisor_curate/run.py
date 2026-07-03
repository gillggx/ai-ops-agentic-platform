#!/usr/bin/env python3
"""Supervisor curation runner (Phase 5) — offline, PROPOSE-ONLY.

One pass: read curation input from Java → Haiku proposes MERGE / CORRECT /
PRUNE / PROMOTE / DOC_REVISE → deterministic validation → queue into
supervisor_actions (status=proposed). A human reviews in /supervisor.

Usage (on EC2, from /opt/aiops):
    JAVA_INTERNAL_TOKEN=$(grep ^JAVA_INTERNAL_TOKEN= python_ai_sidecar/.env | cut -d= -f2-) \
        venv_sidecar/bin/python -m tools.supervisor_curate.run

Weekly cron (documented, not auto-installed — pair with supervisor_report):
    0 8 * * 1  cd /opt/aiops && JAVA_INTERNAL_TOKEN=... \
               venv_sidecar/bin/python -m tools.supervisor_curate.run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one supervisor curation pass")
    ap.add_argument("--java-base", default=os.environ.get(
        "JAVA_API_URL", "http://localhost:8002").rstrip("/"))
    args = ap.parse_args()

    token = os.environ.get("JAVA_INTERNAL_TOKEN", "")
    if not token:
        print("ERROR: export JAVA_INTERNAL_TOKEN first "
              "(see python_ai_sidecar/.env)", file=sys.stderr)
        return 2

    from python_ai_sidecar.supervisor_curation.proposer import run_curation

    res = asyncio.run(run_curation(args.java_base, token))
    print(f"proposed={res.proposed} deduped={res.deduped} "
          f"skipped_invalid={res.skipped_invalid} "
          f"model={res.llm_model} tokens={res.input_tokens}/{res.output_tokens}")
    for e in res.errors:
        print(f"  [error] {e}", file=sys.stderr)
    return 0 if not res.errors else 1


if __name__ == "__main__":
    sys.exit(main())
