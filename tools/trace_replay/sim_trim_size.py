"""Offline size simulation for the trim_sample_rows variant (no LLM).

Applies the transform to every phase-loop decision-point user_msg captured
in a directory of build traces and reports the char/token reduction. Run on
EC2 where the traces live:

    python3 -m tools.trace_replay.sim_trim_size /tmp/builder-traces

Self-test (synthetic row) runs first so a broken transform is caught before
the aggregate numbers are trusted.
"""
from __future__ import annotations

import glob
import json
import os
import sys

# allow `python3 tools/trace_replay/sim_trim_size.py` from repo root
sys.path.insert(0, os.getcwd())

from tools.trace_replay.types import LLMInput
from tools.trace_replay.variants.trim_sample_rows import trim_sample_rows, _trim_block


def _tok(s: str) -> int:
    return len(s) // 4  # rough chars->tokens proxy


def _self_test() -> None:
    row = (
        'Schema (this run):\n| col | type | description |\n'
        '| eventTime | string | ts |\n| DC | dict | sensors |\n\n'
        'Sample (2 rows):\n'
        'row 0: {"eventTime": "2026-06-16T04:45:23", "toolID": "EQP-01", '
        '"spc_status": "OOC", "DC": {"chamberID": "CH1", "p1": 1.2, "p2": 3.4, '
        '"p3": 5.6}, "spc_charts": [{"name": "xbar", "v": 1}, {"name": "r", "v": 2}]}\n'
        'row 1: {"eventTime": "2026-06-16T04:40:00", "toolID": "EQP-01", '
        '"spc_status": "PASS", "DC": {"chamberID": "CH1", "p1": 9.9}}\n'
    )
    out = _trim_block(row)
    assert "| eventTime | string | ts |" in out, "schema table must be untouched"
    assert "EQP-01" in out and "OOC" in out, "scalar cols must survive"
    assert "…4 keys…" in out, "DC nested dict must collapse"
    assert "…2 items…" in out, "spc_charts list must collapse"
    assert '"p1": 1.2' not in out, "nested sensor values must be gone"
    print("[self-test] PASS — schema + scalars kept, nested collapsed\n")


def main(trace_dir: str) -> int:
    _self_test()
    files = sorted(glob.glob(os.path.join(trace_dir, "*.json")))
    rows = []
    tot_before = tot_after = 0
    n_decision = 0
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        calls = []

        def walk(o):
            if isinstance(o, dict):
                if "input_tokens" in o and "node" in o:
                    calls.append(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
        for c in calls:
            um = c.get("user_msg") or ""
            if "Sample (" not in um:
                continue  # no canvas sample bloat → nothing to trim
            after = _trim_block(um)
            b, a = len(um), len(after)
            if a >= b:
                continue
            n_decision += 1
            tot_before += b
            tot_after += a
            rows.append((os.path.basename(f), c.get("phase_id"), c.get("round"), b, a))
    rows.sort(key=lambda r: r[3] - r[4], reverse=True)
    print("=== top 12 obs by absolute reduction ===")
    print("%-42s %-5s %-4s %8s %8s %6s" % ("trace", "phase", "rnd", "before", "after", "cut%"))
    for name, pid, rnd, b, a in rows[:12]:
        print("%-42s %-5s %-4s %8d %8d %5.0f%%" % (name[:42], str(pid), str(rnd), b, a, (b - a) / b * 100))
    print()
    print("=== aggregate over %d decision-point obs (with canvas sample) ===" % n_decision)
    print("  chars : %9d -> %9d   (cut %.0f%%)" % (tot_before, tot_after, (tot_before - tot_after) / max(tot_before, 1) * 100))
    print("  ~tok  : %9d -> %9d   (saved ~%d tok)" % (_tok_total(tot_before), _tok_total(tot_after), _tok_total(tot_before) - _tok_total(tot_after)))
    if n_decision:
        print("  avg per obs: %d -> %d chars (~%d tok saved/obs)" % (
            tot_before // n_decision, tot_after // n_decision,
            (_tok_total(tot_before) - _tok_total(tot_after)) // n_decision))
    return 0


def _tok_total(chars: int) -> int:
    return chars // 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/builder-traces"))
