"""CLI entry — `python -m tools.trace_replay --trace ...`.

Run multiple variants against one captured LLM call from a build trace
and tally the results. Pairs with BuildTracer (graph_build/trace.py).
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from . import loader, runner, report
from .types import LLMInput
from .variants import VARIANT_REGISTRY


def _parse_target(target: str | None) -> dict[str, Any]:
    """Parse `<node>[:phase=<id>][:round=<n>][:index=<n>]` -> filters dict."""
    if not target:
        return {}
    parts = target.split(":")
    out: dict[str, Any] = {"node": parts[0] or None}
    for kv in parts[1:]:
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        if k == "round":
            try:
                out["round"] = int(v)
            except ValueError:
                pass
        elif k == "phase":
            out["phase_id"] = v
        elif k == "index":
            try:
                out["index"] = int(v)
            except ValueError:
                pass
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools.trace_replay",
        description=(
            "Replay an LLM call from a build trace under controlled "
            "variants. Use to test 'does this prompt change actually shift "
            "behaviour?' empirically."
        ),
    )
    p.add_argument("--trace", required=True, help="Path to trace JSON file.")
    p.add_argument(
        "--target", default=None,
        help=(
            "Which LLM call to replay. Format: <node>[:phase=<id>][:round=<n>]"
            " e.g. agentic_phase_loop:phase=p1:round=1. Default: last call."
        ),
    )
    p.add_argument(
        "--variants", nargs="+", default=["identity"],
        help=(
            "Variant names from the registry: "
            + ", ".join(sorted(VARIANT_REGISTRY.keys()))
        ),
    )
    p.add_argument("--reps", type=int, default=3, help="Reps per variant.")
    p.add_argument("--out", default=None, help="JSON output path (optional).")
    p.add_argument(
        "--list-calls", action="store_true",
        help="List all LLM calls in trace and exit (no replay).",
    )
    args = p.parse_args(argv)

    trace = loader.load_trace(args.trace)

    if args.list_calls:
        calls = loader.list_llm_calls(trace)
        print(f"# {len(calls)} LLM call(s) in {args.trace}:")
        for i, c in enumerate(calls):
            print(
                f"  [{i}] node={c.get('node'):<25} "
                f"phase={c.get('phase_id') or '-':<6} "
                f"round={c.get('round') or '-'}  "
                f"in={c.get('input_tokens')} out={c.get('output_tokens')}"
            )
        return 0

    # Resolve variants
    variants: list[tuple[str, Any]] = []
    for name in args.variants:
        if name not in VARIANT_REGISTRY:
            print(f"ERROR: unknown variant '{name}'. Available: "
                  f"{sorted(VARIANT_REGISTRY.keys())}", file=sys.stderr)
            return 2
        variants.append((name, VARIANT_REGISTRY[name]))

    # Load call + reconstruct system + tools
    filters = _parse_target(args.target)
    call = loader.pick_llm_call(trace, **filters)
    node = call.get("node") or "(unknown)"
    sys_text, tool_specs = runner.get_system_and_tools_for_node(node)
    if not sys_text:
        print(f"WARN: no system prompt resolver for node={node}", file=sys.stderr)

    base = loader.build_llm_input_from_call(
        call,
        system_loader_for_node={node: sys_text},
        tools_loader_for_node={node: tool_specs} if tool_specs else None,
    )
    print(
        f"\n[replay] trace={args.trace}\n"
        f"        node={node} phase={call.get('phase_id')} round={call.get('round')}\n"
        f"        original_pick={base.meta.get('original_pick')}\n"
        f"        variants={[n for n, _ in variants]}  reps={args.reps}\n"
        f"        user_msg_len={len(base.user_msg)} system_len={len(base.system)}\n"
    )

    results = asyncio.run(runner.run_experiment(base, variants, args.reps))
    report.print_summary(results)

    if args.out:
        out_path = report.write_json(
            results=results,
            meta={
                "trace": str(args.trace),
                "node": node,
                "phase_id": call.get("phase_id"),
                "round": call.get("round"),
                "original_pick": base.meta.get("original_pick"),
                "variants": [n for n, _ in variants],
                "reps": args.reps,
            },
            out_path=args.out,
        )
        print(f"[replay] results written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
