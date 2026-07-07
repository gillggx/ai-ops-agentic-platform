"""Skill 參數化 (真 Skill 化 F1, 2026-07-08).

A chat-built pipeline hardcodes its identity params (tool_id='EQP-01' …),
so the saved skill is a recording, not a tool. This module turns concrete
source-node identity params into declared PipelineInputs ($name refs) —
the executor has resolved $name since Phase 4-B0; nothing downstream
changes.

Scope decision (user, 2026-07-08): candidates come from SOURCE-node
identity params only — deterministic, read straight from the params;
no LLM involved in identification. Names/descriptions are templated.
"""
from __future__ import annotations

import copy
from typing import Any

# Identity params on source blocks — the swappable surface (裁決 1: 看 source).
# key → (input type, 中文 label template)
IDENTITY_KEYS: dict[str, tuple[str, str]] = {
    "tool_id": ("string", "機台 ID"),
    "lot_id": ("string", "批次 ID"),
    "step": ("string", "站點"),
    "time_range": ("string", "時間範圍（如 7d / 24h）"),
    "limit": ("number", "筆數上限"),
    "chart_name": ("string", "SPC chart 名稱"),
    "kind": ("string", "物件類型"),
    "event_filter": ("string", "事件範圍"),
}


def _source_node_ids(pj: dict[str, Any]) -> set[str]:
    has_inbound = {(e.get("to") or {}).get("node") for e in (pj.get("edges") or [])}
    return {str(n.get("id")) for n in (pj.get("nodes") or [])
            if n.get("id") and n.get("id") not in has_inbound}


def find_candidates(pj: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic candidate scan. Grouped by param key — the same key on
    two source nodes becomes ONE shared input bound to both sites."""
    sources = _source_node_ids(pj)
    declared = {i.get("name") for i in (pj.get("inputs") or [])}
    grouped: dict[str, dict[str, Any]] = {}
    for n in pj.get("nodes") or []:
        nid = str(n.get("id"))
        if nid not in sources:
            continue
        for key, val in (n.get("params") or {}).items():
            if key not in IDENTITY_KEYS:
                continue
            if isinstance(val, str) and val.startswith("$"):
                continue  # already parameterized
            if isinstance(val, (list, dict)):
                continue  # v1: scalars only（step list 等結構值不開放）
            if val is None or val == "":
                continue
            if key in declared:
                continue
            typ, label = IDENTITY_KEYS[key]
            g = grouped.setdefault(key, {
                "name": key,
                "type": typ,
                "label": label,
                "description": f"{label}（預設 {val}）",
                "default": val,
                "example": val,
                "sites": [],
            })
            g["sites"].append({"node": nid, "param": key})
            # first-seen value wins for default; mismatched values across
            # nodes are surfaced so the human sees the conflict.
            if g["default"] != val:
                g.setdefault("conflicting_values", []).append(val)
    return list(grouped.values())


def apply_parameterize(
    pj: dict[str, Any], accept: list[str],
) -> tuple[dict[str, Any] | None, str]:
    """Apply accepted candidates: declare inputs + replace sites with $name.

    Pure + validated: unknown names rejected; original object untouched."""
    if not accept:
        return None, "empty accept list"
    cands = {c["name"]: c for c in find_candidates(pj)}
    unknown = [a for a in accept if a not in cands]
    if unknown:
        return None, f"not parameterizable: {unknown} (candidates: {sorted(cands)})"
    out = copy.deepcopy(pj)
    inputs = list(out.get("inputs") or [])
    node_by_id = {str(n.get("id")): n for n in (out.get("nodes") or [])}
    for name in accept:
        c = cands[name]
        inputs.append({
            "name": c["name"],
            "type": c["type"],
            "required": False,
            "default": c["default"],
            "description": c["description"],
            "example": c["example"],
        })
        for site in c["sites"]:
            node = node_by_id.get(site["node"])
            if node is None:
                continue
            params = dict(node.get("params") or {})
            params[site["param"]] = f"${name}"
            node["params"] = params
    out["inputs"] = inputs
    return out, ""
