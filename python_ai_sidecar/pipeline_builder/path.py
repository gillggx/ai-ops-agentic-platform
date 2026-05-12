"""Path-based access for hierarchical pipeline data.

The pipeline canonical data type is `list[dict]` where dict values can be
arbitrarily nested (scalar | list | dict). A "table" is the degenerate case
where all dicts are flat — but the runtime makes no such assumption.

Path grammar:
    "tool_id"                  scalar at top level
    "spc_summary.ooc_count"    nested scalar via dot
    "spc_charts[]"             entire array (returns list)
    "spc_charts[].name"        plucked field from every array element

Returned values:
    get_path(obj, path) -> Any | None
        Returns the leaf value. For array paths, returns list of plucked
        values (with None for elements where the path doesn't resolve).

    walk_paths(schema) -> list[str]
        Enumerate every legal leaf path through a JSON-Schema-ish dict.
        Used by `_columns_for_block_port` to generate path catalogs for
        the LLM.

Safety: path tokens must match [a-zA-Z0-9_]+ (plus `[]` array marker).
No __proto__ / __class__ / dunder access — paths are read-only.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_]+$")
_PATH_RE = re.compile(r"^[a-zA-Z0-9_.\[\]]+$")


def is_valid_path(path: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    if not _PATH_RE.match(path):
        return False
    # forbid leading dot / dunder segment
    for seg in re.split(r"[.\[\]]", path):
        if not seg:
            continue
        if seg.startswith("_") or not _TOKEN_RE.match(seg):
            return False
    return True


def _parse(path: str) -> list[tuple[str, bool]]:
    """Tokenize path into [(name, is_array), ...].

    "a.b[].c" → [("a", False), ("b", True), ("c", False)]
    "spc_charts[]" → [("spc_charts", True)]
    """
    out: list[tuple[str, bool]] = []
    # Replace `[]` with a marker we can detect after splitting on `.`
    parts = path.split(".")
    for p in parts:
        is_array = p.endswith("[]")
        name = p[:-2] if is_array else p
        if not name:
            continue
        out.append((name, is_array))
    return out


def get_path(obj: Any, path: str) -> Any:
    """Resolve a path on a single object. Returns None for missing keys.

    - "a.b" walks into nested dicts
    - "a[]" returns the list at key `a` (if present), else None
    - "a[].b" plucks `b` from every element of `a` (None if missing per elem)
    - chained arrays: "a[].b[].c" returns flattened list of c values
    """
    if not is_valid_path(path):
        return None
    tokens = _parse(path)
    if not tokens:
        return None
    current: Any = obj
    for i, (name, is_array) in enumerate(tokens):
        if current is None:
            return None
        if isinstance(current, list):
            # We're at a list — pluck name from each element
            collected: list[Any] = []
            remaining = [(name, is_array), *tokens[i + 1:]]
            for elem in current:
                val = _resolve_remaining(elem, remaining)
                if isinstance(val, list):
                    collected.extend(val)
                else:
                    collected.append(val)
            return collected
        if not isinstance(current, dict):
            return None
        if name not in current:
            return None
        current = current[name]
        if is_array:
            # caller wants the array as-is OR there's more after
            if i == len(tokens) - 1:
                return current if isinstance(current, list) else None
            if not isinstance(current, list):
                return None
            # next token plucks from elements
            collected = []
            for elem in current:
                val = _resolve_remaining(elem, tokens[i + 1:])
                if isinstance(val, list):
                    collected.extend(val)
                else:
                    collected.append(val)
            return collected
    return current


def _resolve_remaining(obj: Any, tokens: list[tuple[str, bool]]) -> Any:
    """Helper: continue resolving from an arbitrary point in a token stream."""
    cur: Any = obj
    for i, (name, is_array) in enumerate(tokens):
        if cur is None:
            return None
        if not isinstance(cur, dict):
            return None
        if name not in cur:
            return None
        cur = cur[name]
        if is_array:
            if i == len(tokens) - 1:
                return cur if isinstance(cur, list) else None
            if not isinstance(cur, list):
                return None
            out: list[Any] = []
            for elem in cur:
                v = _resolve_remaining(elem, tokens[i + 1:])
                if isinstance(v, list):
                    out.extend(v)
                else:
                    out.append(v)
            return out
    return cur


def walk_paths(schema: Any, prefix: str = "") -> list[str]:
    """Enumerate leaf paths through a schema-like dict.

    Accepts:
      - JSON-Schema-ish: {"type": "object", "properties": {...}}
      - Bare dict where values are subschemas
      - List of {"name": ..., "type": ..., "items"?: ...} (block_registry style)

    Returns paths in declaration order. Stops at scalar leaves; arrays of
    objects emit "<prefix>[].field" entries; arrays of scalars emit "<prefix>"
    plus an implicit "<prefix>[]" alias (caller decides which to display).
    """
    paths: list[str] = []
    if schema is None:
        if prefix:
            paths.append(prefix)
        return paths
    # ── List-of-field-descriptors (block output_columns_hint format)
    if isinstance(schema, list):
        for entry in schema:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            t = entry.get("type") or "scalar"
            child_prefix = f"{prefix}.{name}" if prefix else name
            if t == "array":
                items = entry.get("items")
                if isinstance(items, list):
                    paths.extend(walk_paths(items, f"{child_prefix}[]"))
                elif isinstance(items, dict):
                    paths.extend(walk_paths(items, f"{child_prefix}[]"))
                else:
                    paths.append(f"{child_prefix}[]")  # array of scalars
            elif t == "object":
                paths.extend(walk_paths(entry.get("properties") or entry.get("items"), child_prefix))
            else:
                paths.append(child_prefix)
        return paths
    # ── JSON-Schema-ish dict
    if isinstance(schema, dict):
        if "properties" in schema:
            for k, v in schema["properties"].items():
                child_prefix = f"{prefix}.{k}" if prefix else k
                paths.extend(walk_paths(v, child_prefix))
            return paths
        t = schema.get("type")
        if t == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                paths.extend(walk_paths(items, f"{prefix}[]"))
            else:
                paths.append(f"{prefix}[]")
            return paths
        if t == "object":
            paths.extend(walk_paths(schema.get("properties") or {}, prefix))
            return paths
        # Bare "properties map" — dict without 'type'/'properties' keys, where
        # each value is itself a sub-schema. Treat each key as a property.
        # Heuristic: every value is a dict (signals nested sub-schema).
        if t is None and schema and all(isinstance(v, dict) for v in schema.values()):
            for k, v in schema.items():
                child_prefix = f"{prefix}.{k}" if prefix else k
                paths.extend(walk_paths(v, child_prefix))
            return paths
        if prefix:
            paths.append(prefix)
        return paths
    if prefix:
        paths.append(prefix)
    return paths


def discover_paths_from_data(data: Any, prefix: str = "", max_depth: int = 4) -> list[str]:
    """Best-effort path discovery from actual data (used when schema is unknown).

    Walks a sample record to enumerate leaf paths. Stops at max_depth to
    avoid pathological recursion. Doesn't dedupe — caller does.
    """
    if max_depth <= 0:
        if prefix:
            return [prefix]
        return []
    paths: list[str] = []
    if isinstance(data, dict):
        if not data and prefix:
            return [prefix]
        for k, v in data.items():
            if k.startswith("_"):
                continue
            child = f"{prefix}.{k}" if prefix else k
            paths.extend(discover_paths_from_data(v, child, max_depth - 1))
    elif isinstance(data, list):
        if not data and prefix:
            return [f"{prefix}[]"]
        # Sample first element only — we assume homogeneous arrays
        sample = data[0] if data else None
        if isinstance(sample, (dict, list)):
            paths.extend(discover_paths_from_data(sample, f"{prefix}[]", max_depth - 1))
        elif prefix:
            paths.append(f"{prefix}[]")
    else:
        if prefix:
            paths.append(prefix)
    return paths


def top_level_key(path: str) -> str:
    """First segment of a path — useful for "does this record at all touch X?" checks."""
    if not path:
        return ""
    for ch in path:
        if ch in (".", "["):
            return path[: path.index(ch)] if ch == "." else path[: path.index("[")]
    return path


def flatten_record(record: dict, max_depth: int = 3) -> dict[str, Any]:
    """Flatten a nested dict into a single-level dict whose keys are paths.

    Used by the table renderer. Arrays become path[].field entries with
    aggregated values (list-of-values rather than separate rows). Caller
    can choose how to display — UI layer handles unnesting via `[+]`
    expansion.
    """
    out: dict[str, Any] = {}

    def _walk(obj: Any, prefix: str, depth: int) -> None:
        if depth <= 0 or obj is None:
            if prefix:
                out[prefix] = obj
            return
        if isinstance(obj, dict):
            if not obj and prefix:
                out[prefix] = {}
                return
            for k, v in obj.items():
                child = f"{prefix}.{k}" if prefix else k
                _walk(v, child, depth - 1)
        elif isinstance(obj, list):
            # leave arrays as-is so UI can render [+] expansion
            if prefix:
                out[prefix] = obj
        else:
            if prefix:
                out[prefix] = obj

    _walk(record, "", max_depth)
    return out


def _set_via_tokens(obj: Any, tokens: list[tuple[str, bool]], value: Any) -> None:
    """Helper: walk obj following tokens, creating dicts along the way,
    then set the leaf. Array paths set value on EACH element."""
    if not tokens:
        return
    cur: Any = obj
    for i, (name, is_array) in enumerate(tokens):
        last = i == len(tokens) - 1
        if isinstance(cur, list):
            for elem in cur:
                _set_via_tokens(elem, tokens[i:], value)
            return
        if not isinstance(cur, dict):
            return
        if last and not is_array:
            cur[name] = value
            return
        if is_array:
            if name not in cur or not isinstance(cur[name], list):
                return  # can't broadcast into non-list
            for elem in cur[name]:
                _set_via_tokens(elem, tokens[i + 1:], value)
            return
        if name not in cur or not isinstance(cur[name], dict):
            cur[name] = {}
        cur = cur[name]


def set_path(obj: dict, path: str, value: Any) -> None:
    """Mutate obj to set value at path. Used by block_compute when writing
    a new derived column at a nested location (e.g. column='spc_summary.derived_x').
    """
    if not is_valid_path(path):
        return
    tokens = _parse(path)
    _set_via_tokens(obj, tokens, value)


# ── DataFrame helpers ────────────────────────────────────────────────────
#
# The pipeline canonical type is `list[dict]` semantically, but at runtime
# pandas DataFrames are still used to glue blocks together (preserves the
# existing 27-block executor architecture). When a DataFrame column holds
# dict/list values (object dtype), these helpers let blocks address into
# those values via path syntax — no need to flatten/unnest before filter
# or sort.


def get_column_series(df, path: str):
    """Resolve a (possibly nested) path against a DataFrame and return a Series.

    - Flat path "tool_id" → df["tool_id"] (unchanged behavior)
    - Nested "spc_summary.ooc_count" → df["spc_summary"].apply(get_path inner)
    - Array path "spc_charts[].name" → Series where each cell is a list

    Raises KeyError if the head column is missing — caller turns into
    BlockExecutionError with a friendly message.
    """
    import pandas as pd  # local import: path.py shouldn't force pandas dep
    if df is None or path is None:
        raise KeyError(path)
    if not isinstance(df, pd.DataFrame):
        raise TypeError("get_column_series expects a DataFrame")
    if not path:
        raise KeyError(path)

    # Flat case — fast path
    if "." not in path and "[]" not in path:
        if path in df.columns:
            return df[path]
        raise KeyError(path)

    # Nested case
    head = path.split(".", 1)[0].split("[", 1)[0]
    if head not in df.columns:
        raise KeyError(head)
    tail = path[len(head):]
    if tail.startswith("[]"):
        # head is supposed to be an array column; we just return that — caller
        # handles list-of-X. If the path is exactly "head[]" we return as-is.
        if tail == "[]":
            return df[head]
        tail = tail[2:]
        if tail.startswith("."):
            tail = tail[1:]
        # head[].field → pluck per element
        return df[head].apply(
            lambda v: [get_path(e, tail) for e in v] if isinstance(v, list) else None
        )
    if tail.startswith("."):
        tail = tail[1:]
    return df[head].apply(lambda v: get_path(v, tail))


def column_exists(df, path: str) -> bool:
    """True if path resolves on the DataFrame's columns OR addresses into
    nested dict/list values therein. Used by validators to confirm a
    column-ref before runtime."""
    import pandas as pd
    if df is None or not isinstance(df, pd.DataFrame) or not path:
        return False
    head = path.split(".", 1)[0].split("[", 1)[0]
    if head not in df.columns:
        return False
    if "." not in path and "[]" not in path:
        return True
    # Sample first non-null value to confirm shape — best-effort.
    series = df[head]
    sample = next((v for v in series if v is not None), None)
    if sample is None:
        # empty column — still accept (will fail at runtime if shape wrong)
        return True
    tail = path[len(head):]
    if tail.startswith("[]"):
        if not isinstance(sample, list):
            return False
        if tail == "[]":
            return True
        tail = tail[2:].lstrip(".")
        # need to peek into first element
        elem = next((e for e in sample if e is not None), None)
        if elem is None:
            return True
        return get_path(elem, tail) is not None or _path_could_exist(elem, tail)
    if tail.startswith("."):
        tail = tail[1:]
    return get_path(sample, tail) is not None or _path_could_exist(sample, tail)


def _path_could_exist(obj: Any, tail: str) -> bool:
    """Permissive check — returns True if tail looks navigable on obj's shape.
    Used so we accept columns whose sample value happens to be None for the
    leaf field. Walks dict/list structure as far as it can."""
    if not tail or not isinstance(obj, (dict, list)):
        return False
    tokens = _parse(tail)
    cur = obj
    for name, is_array in tokens:
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict):
            return False
        if name in cur:
            cur = cur[name]
            if is_array and not isinstance(cur, list):
                return False
        else:
            return False
    return True


def expand_array_column(df, path: str):
    """Like `pandas.DataFrame.explode` but path-aware.

    For path "spc_charts[]" (or "spc_charts"), returns a new DataFrame where
    each list element becomes its own row, with all sibling columns broadcast.
    If the elements are dicts, their keys become new columns at the top level.

    Used by block_unnest.
    """
    import pandas as pd
    if df is None or not isinstance(df, pd.DataFrame):
        raise TypeError("expand_array_column expects a DataFrame")
    head = path.split(".", 1)[0].split("[", 1)[0]
    if head not in df.columns:
        raise KeyError(head)
    exploded = df.explode(head, ignore_index=True)
    # If exploded col is dict-typed, lift its keys to top-level
    sample = next((v for v in exploded[head] if isinstance(v, dict)), None)
    if sample is None:
        return exploded
    lifted = pd.json_normalize(exploded[head].where(exploded[head].notna(), {}))
    out = exploded.drop(columns=[head]).reset_index(drop=True)
    lifted = lifted.reset_index(drop=True)
    return pd.concat([out, lifted], axis=1)
