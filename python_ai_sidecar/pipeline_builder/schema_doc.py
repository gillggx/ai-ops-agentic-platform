"""v30 schema documentation — usage-oriented col descriptions for LLM context.

Two purposes:
  1. format_col_box(col_meta) — render a single col as a 4-block markdown box
     (type / what / usage / anti-usage). Used in seed.py block descriptions
     for source-category blocks where output cols are deterministic.
  2. infer_runtime_schema(df, block_spec) — at preview time, generate a
     per-node runtime schema doc (cols + inferred types + sample). Stored
     in exec_trace[lid].runtime_schema_md and injected into next LLM prompt.

No emoji. Pure-text markers: [best] / [ok] / [no] / [warn].
"""
from __future__ import annotations

from typing import Any, Mapping
import json


# ---------------------------------------------------------------------------
# 1. Static schema doc — 4-block col box for source-category blocks
# ---------------------------------------------------------------------------

# Usage line marker prefixes. Order in render: best > ok > no > warn.
_MARKER_BEST = "[best]"
_MARKER_OK = "[ok]"
_MARKER_NO = "[no]"
_MARKER_WARN = "[warn]"

_BOX_WIDTH = 76  # max chars per box line; longer lines wrap


def format_col_box(meta: Mapping[str, Any]) -> str:
    """Render a single col as a 4-block schema box (markdown).

    `meta` shape:
      {
        "col": str,             # required, column name
        "type": str,            # required, e.g. 'enum["PASS"|"OOC"]'
        "what": str,            # required, 1-line semantic
        "usage": [               # list of {marker, text}
          {"marker": "best" | "ok" | "no" | "warn", "text": "..."},
          ...
        ],
      }

    Returns:
      Multi-line string (no trailing newline). Box-drawing borders ASCII-safe.
    """
    col = str(meta.get("col") or "")
    typ = str(meta.get("type") or "")
    what = str(meta.get("what") or "")
    usage_items = list(meta.get("usage") or [])

    header = f"col: {col}"
    type_line = f"type: {typ}"
    what_line = f"what: {what}"

    usage_lines = ["usage:"]
    for item in usage_items:
        if not isinstance(item, dict):
            continue
        marker_key = str(item.get("marker") or "ok").lower()
        marker = {
            "best": _MARKER_BEST,
            "ok": _MARKER_OK,
            "no": _MARKER_NO,
            "warn": _MARKER_WARN,
        }.get(marker_key, _MARKER_OK)
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        usage_lines.append(f"  {marker} {text}")

    lines = [header, type_line, what_line, *usage_lines]
    return _wrap_in_box(lines)


def _wrap_in_box(lines: list[str], width: int = _BOX_WIDTH) -> str:
    """Wrap lines in an ASCII box. Box lines are not truncated; just shown raw
    with rule lines top/bottom. Output is meant to be embedded in markdown
    fenced code or pre-formatted contexts.
    """
    top = "+" + "-" * (width - 2) + "+"
    out = [top]
    for ln in lines:
        # Don't strict-pad; keep box visually consistent with raw content
        out.append("| " + ln)
    out.append(top)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 2. Runtime schema — per-node, generated after executor preview
# ---------------------------------------------------------------------------

_MAX_SAMPLE_ROWS = 2     # LLM rarely needs > 2 rows; 3 is hard cap
_MAX_COLS_LISTED = 30    # cap col table size
_MAX_VAL_REPR = 80       # truncate each cell value in sample
_ENUM_DISTINCT_CAP = 8   # report enum if distinct values <= this


def infer_runtime_schema(
    df: Any,                       # pandas.DataFrame (typed at call-site)
    block_spec: Mapping[str, Any] | None = None,
    node_id: str | None = None,
) -> str:
    """Generate the runtime schema markdown for a node's actual output.

    Inferred:
      - col type (string/int/float/bool/list/dict/null)
      - unique count for stringish cols
      - enum distribution if distinct <= _ENUM_DISTINCT_CAP
      - nested shape (list[dict]/dict) — note keys
    Merged from block_spec:
      - usage hint per col (looked up from the block's column-level doc)

    Returns markdown string. Empty string if df invalid.
    """
    # pandas import deferred — schema_doc.py shouldn't crash if pandas missing
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        return ""

    if df is None:
        return ""
    try:
        n_rows = int(len(df))
        cols = list(df.columns)
    except Exception:
        return ""

    block_id = (block_spec or {}).get("name") or ""
    col_usage_hints = _extract_col_usage_hints(block_spec)
    # v30.8 (2026-05-16): prefer explicit column_docs `type` over sample-inferred.
    # Sample-inferred enum can mislead LLM when sample only shows partial values
    # (e.g. spc_status enum['PASS'=5] hides the 'OOC' option a real OOC event
    # would have). column_docs declares the full enum honestly.
    col_doc_types = _extract_col_doc_types(block_spec)

    header_lines: list[str] = []
    nid = node_id or "?"
    pid = block_id or "?"
    header_lines.append(f"{nid} [{pid}] -> {n_rows} rows x {len(cols)} cols")
    header_lines.append("")
    header_lines.append("Schema (this run):")

    # Build col rows
    table_lines = ["| col | inferred type | usage hint |"]
    table_lines.append("|---|---|---|")
    for c in cols[:_MAX_COLS_LISTED]:
        # Prefer explicit doc type when present; fall back to sample inference.
        typ = col_doc_types.get(c) or _infer_col_type(df, c)
        hint = col_usage_hints.get(c, "")
        # Escape pipes inside content
        c_esc = str(c).replace("|", "\\|")
        typ_esc = typ.replace("|", "\\|")
        hint_esc = hint.replace("|", "\\|").replace("\n", " ")
        table_lines.append(f"| {c_esc} | {typ_esc} | {hint_esc} |")
    if len(cols) > _MAX_COLS_LISTED:
        table_lines.append(f"| ... +{len(cols) - _MAX_COLS_LISTED} more cols | | |")

    # Sample rows (cap _MAX_SAMPLE_ROWS, value truncation)
    sample_lines: list[str] = []
    sample_lines.append("")
    sample_lines.append(f"Sample ({min(n_rows, _MAX_SAMPLE_ROWS)} rows):")
    try:
        sample_rows = df.head(_MAX_SAMPLE_ROWS).to_dict(orient="records")
        for i, row in enumerate(sample_rows):
            truncated = {k: _truncate_value(v) for k, v in row.items()}
            sample_lines.append(f"row {i}: {json.dumps(truncated, ensure_ascii=False, default=str)}")
    except Exception as ex:  # noqa: BLE001
        sample_lines.append(f"(sample render failed: {ex})")

    return "\n".join(header_lines + table_lines + sample_lines)


def _extract_col_doc_types(block_spec: Mapping[str, Any] | None) -> dict[str, str]:
    """v30.8: extract explicit `type` from block_spec.column_docs[].

    Returned types override sample-inferred types in runtime_schema_md.
    Use case: spc_status's true type is `enum["PASS"|"OOC"]` but a sample
    where every row is PASS would infer `enum['PASS'=5]` — misleading LLM.
    """
    if not block_spec:
        return {}
    out: dict[str, str] = {}
    for entry in (block_spec.get("column_docs") or []):
        if not isinstance(entry, dict):
            continue
        col = entry.get("col")
        typ = entry.get("type")
        if col and typ and isinstance(typ, str):
            out[col] = typ.strip()
    return out


def _extract_col_usage_hints(block_spec: Mapping[str, Any] | None) -> dict[str, str]:
    """Pull per-col usage hint from block_spec.column_docs if present.

    Schema we expect in seed.py for source blocks:
      {
        "column_docs": [
          {"col": "spc_status", "type": "...", "what": "...", "usage": [...]},
          ...
        ]
      }
    Returns {col_name: short_hint_string}.
    """
    if not block_spec:
        return {}
    docs = block_spec.get("column_docs") or []
    out: dict[str, str] = {}
    for entry in docs:
        if not isinstance(entry, dict):
            continue
        col = entry.get("col")
        if not col:
            continue
        # v30.9 (2026-05-16): show ALL [best]/[ok] hints (joined with " ; ")
        # instead of just the first [best]. Single-[best] was hiding
        # alternative paths (e.g. spc_charts had a direct unnest-count path
        # added as [ok] that LLM never saw because only first [best] shown).
        usage = entry.get("usage") or []
        hint_parts: list[str] = []
        for u in usage:
            if not isinstance(u, dict):
                continue
            marker = str(u.get("marker") or "").lower()
            text = u.get("text") or ""
            if not text:
                continue
            if marker == "best":
                hint_parts.append(f"[best] {text}")
            elif marker == "ok":
                hint_parts.append(f"[ok] {text}")
            elif marker == "warn":
                hint_parts.append(f"[warn] {text}")
            # [no] omitted from runtime schema — keep prompt clean
        if hint_parts:
            hint = " ; ".join(hint_parts)
        else:
            hint = str(entry.get("what") or "")
        out[col] = hint
    return out


def _infer_col_type(df: Any, col: str) -> str:
    """Infer a compact type string for a column.

    For stringish cols, report unique count + enum distribution if small.
    For nested cols, describe shape (list[dict]/dict) + leaf keys when consistent.
    """
    # Get a sample value first (works for any dtype incl. lists/dicts).
    try:
        series = df[col]
        sample_val = None
        for v in series:
            # pandas might wrap None in NaN; ignore both
            if v is None:
                continue
            try:
                # NaN check without importing numpy: NaN != NaN
                if v != v:
                    continue
            except Exception:
                pass
            sample_val = v
            break
    except Exception:
        return "?"

    # List / dict cols — describe shape (do this BEFORE nunique which would
    # crash on unhashable types).
    if isinstance(sample_val, list):
        if sample_val and isinstance(sample_val[0], dict):
            keys = list(sample_val[0].keys())[:_ENUM_DISTINCT_CAP]
            return f"list[{len(keys)}-dict {{{', '.join(keys)}}}]"
        return f"list[{type(sample_val[0]).__name__ if sample_val else 'empty'}]"
    if isinstance(sample_val, dict):
        keys = list(sample_val.keys())[:_ENUM_DISTINCT_CAP]
        return f"dict{{{', '.join(keys)}}}"

    # Scalar — now safe to call nunique.
    try:
        non_null = series.dropna()
        n_rows = len(non_null)
        n_unique = non_null.nunique() if hasattr(non_null, "nunique") else 0
    except Exception:
        n_unique = 0
        n_rows = 0

    if sample_val is None:
        return "null"
    if isinstance(sample_val, bool):
        return "bool"
    if isinstance(sample_val, int):
        return "int"
    if isinstance(sample_val, float):
        return "float"
    if isinstance(sample_val, str):
        # Enum extraction only when distinct is meaningfully small AND
        # at least 1 value repeats (n_unique < n_rows). For all-distinct
        # cols (timestamps, IDs), just report 'string [unique:N]'.
        if 0 < n_unique <= _ENUM_DISTINCT_CAP and n_unique < n_rows:
            try:
                counts = non_null.value_counts()
                items = [f"{k!r}={v}" for k, v in counts.items()]
                return f"enum[{', '.join(items)}]"
            except Exception:
                pass
        return f"string [unique:{n_unique}]"
    return type(sample_val).__name__


def _truncate_value(v: Any, depth: int = 0) -> Any:
    """Trim long string repr; recurse into list/dict shallowly.

    v30.8 (2026-05-16): for nested dicts at depth 0 (top-level row values)
    with > _DICT_COLLAPSE_KEYS keys, collapse to a key-list summary instead
    of expanding all values. Stops the sample dump from blowing up with
    APC/DC/RECIPE/FDC/EC sub-dicts (each containing 20-80 sensor parameters
    irrelevant to most phase tasks). LLM can still see the keys and use
    block_pluck / inspect_node_output to drill in if needed.
    """
    if isinstance(v, str) and len(v) > _MAX_VAL_REPR:
        return v[:_MAX_VAL_REPR] + "..."
    if isinstance(v, list):
        if len(v) <= 3:
            return [_truncate_value(x, depth + 1) for x in v]
        return [_truncate_value(x, depth + 1) for x in v[:2]] + [f"...+{len(v)-2} more"]
    if isinstance(v, dict):
        # Top-level large dicts (like APC/DC/RECIPE/FDC/EC blocks in
        # process_history rows) collapse to key summary. depth>0 keeps
        # values for shallow nesting (e.g. spc_summary stays expanded).
        if depth == 0 and len(v) > _DICT_COLLAPSE_KEYS:
            keys = list(v.keys())[:6]
            tail = f"...+{len(v) - 6} more keys" if len(v) > 6 else ""
            return f"<dict {len(v)} keys: {keys}{tail}>"
        return {k: _truncate_value(vv, depth + 1) for k, vv in v.items()}
    return v


_DICT_COLLAPSE_KEYS = 5
