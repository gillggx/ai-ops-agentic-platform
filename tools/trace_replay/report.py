"""Report — print + persist replay results."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .types import ReplayResult


def to_jsonable(results: list[ReplayResult]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        out.append({
            "variant": r.variant,
            "rep": r.rep,
            "tool": r.tool,
            "picked": r.picked,
            "tool_input": r.tool_input,
            "text_blocks": r.text_blocks,
            "duration_ms": r.duration_ms,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "error": r.error,
        })
    return out


def write_json(
    *, results: list[ReplayResult], meta: dict[str, Any], out_path: str | Path,
) -> Path:
    payload = {"meta": meta, "results": to_jsonable(results)}
    p = Path(out_path)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def print_summary(results: list[ReplayResult]) -> None:
    """Console summary: per-variant pick distribution + first-rep text snippets."""
    variants = sorted({r.variant for r in results})
    print()
    print("=" * 70)
    print("REPLAY TALLY")
    print("=" * 70)
    for v in variants:
        picks = Counter(r.picked for r in results if r.variant == v)
        n = sum(picks.values())
        print(f"\n  [{v}] ({n} reps)")
        for pick, count in picks.most_common():
            bar = "█" * count
            print(f"    {count}/{n}  {bar}  {pick}")
    # Show one text snippet per (variant, rep=1) for empathy
    print()
    print("=" * 70)
    print("LLM TEXT REASONING (rep 1 each variant)")
    print("=" * 70)
    for v in variants:
        first = next((r for r in results if r.variant == v and r.rep == 1), None)
        if first and first.text_blocks:
            joined = "\n".join(first.text_blocks)
            preview = joined[:400] + ("…" if len(joined) > 400 else "")
            print(f"\n  [{v}] picked={first.picked}")
            print("    " + preview.replace("\n", "\n    "))
        elif first:
            print(f"\n  [{v}] picked={first.picked}  (no text content emitted)")
    print()
