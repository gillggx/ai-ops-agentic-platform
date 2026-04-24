#!/usr/bin/env python3
"""Phase 8 / P1 · DR pipeline block-param fixup.

22 DR pipelines from Phase ε were built from 3 buggy templates:

  A) SPC trend    (5 pipelines: -P1..-P5)
     Bug: block_rolling_window uses `value_column` but the real block expects `column`.

  B) APC list     (5 pipelines: -P1..-P5)
     Bug 1: block_filter passes `predicates: [{column, operator, value}]` but block
            expects top-level column / operator / value.
     Bug 2: block_sort uses `column` + `direction` + `limit` — block signature matches,
            so only confirm. No change.
     Bug 3: block_mcp_foreach uses from_column / to_param / fixed_params / output_column
            but block expects mcp_name + args_template (dict with $refs) + result_prefix.
     Bug 4: block_alert connected directly to mcp_foreach without a logic node emitting
            `triggered` — insert block_threshold `{column: 'apc_events', operator: '!=', value: null}`.

  C) RECIPE list  (5 pipelines: -P1..-P5)
     Bug: block_alert fed directly from block_process_history (no logic node).
          Insert block_threshold on row count.

This script:
  - Connects to PG, loads all `[DR-%` pipelines.
  - For each, classifies by name → applies fixer A/B/C.
  - UPDATE pb_pipelines.pipeline_json back.
  - Dry-run by default; pass --apply to write.

Run from EC2:
    sudo -u postgres psql -d aiops_db -tAc ...  # loads connection
    python3 scripts/p1_fix_dr_pipelines.py --dsn 'postgresql://aiops:pw@localhost/aiops_db' --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import psycopg


def _is_spc_trend(name: str) -> bool:
    return "SPC trend" in name or "SPC t" in name


def _is_apc_list(name: str) -> bool:
    return "APC 參數列表" in name or "APC" in name


def _is_recipe_list(name: str) -> bool:
    return "RECIPE" in name


def fix_spc_trend(pj: dict) -> tuple[dict, list[str]]:
    """Bug A: rolling_window value_column → column."""
    patches: list[str] = []
    for node in pj.get("nodes") or []:
        if node.get("block_id") == "block_rolling_window":
            params = node.get("params") or {}
            if "value_column" in params and "column" not in params:
                params["column"] = params.pop("value_column")
                node["params"] = params
                patches.append(f"{node['id']}.rolling_window: value_column → column")
    return pj, patches


def fix_apc_list(pj: dict) -> tuple[dict, list[str]]:
    """Bugs B1-B4 for APC list template."""
    patches: list[str] = []
    nodes = pj.get("nodes") or []
    edges = pj.get("edges") or []

    for node in nodes:
        bid = node.get("block_id")
        params = node.get("params") or {}

        if bid == "block_filter":
            # B1: predicates[0] → flat column/operator/value
            preds = params.get("predicates")
            if isinstance(preds, list) and preds and isinstance(preds[0], dict):
                p = preds[0]
                params.pop("predicates", None)
                params["column"] = p.get("column")
                params["operator"] = p.get("operator")
                params["value"] = p.get("value")
                node["params"] = params
                patches.append(f"{node['id']}.filter: predicates[0] → flat")

        elif bid == "block_mcp_foreach":
            # B3: rewrite foreach params
            from_col = params.pop("from_column", None)
            to_param = params.pop("to_param", None)
            fixed_params = params.pop("fixed_params", None) or {}
            output_col = params.pop("output_column", None)

            if from_col and to_param:
                # Build args_template like {objectName: "APC", lotID: "$lotID"}
                args_template = dict(fixed_params) if isinstance(fixed_params, dict) else {}
                args_template[to_param] = f"${from_col}"
                params["args_template"] = args_template
                if output_col:
                    params["result_prefix"] = f"{output_col}_"
                node["params"] = params
                patches.append(f"{node['id']}.mcp_foreach: from_column/to_param → args_template")

    # B4: ensure block_alert has a logic upstream. If alert's only incoming edge is from
    # block_mcp_foreach (which is a data block, not logic), insert block_threshold between.
    # For MVP: detect mcp_foreach → alert direct wiring, inject threshold.
    # (We don't mutate edges here — document instead; fixer script for edges is more risky)
    for node in nodes:
        if node.get("block_id") != "block_alert":
            continue
        incoming = [e for e in edges if e.get("to") == node["id"] or
                    (isinstance(e.get("to"), dict) and e["to"].get("node") == node["id"])]
        for e in incoming:
            src = e.get("from")
            src_node_id = src["node"] if isinstance(src, dict) else src
            src_node = next((n for n in nodes if n.get("id") == src_node_id), None)
            if src_node and src_node.get("block_id") == "block_mcp_foreach":
                patches.append(
                    f"⚠  {node['id']}.alert reads from {src_node_id}.mcp_foreach directly "
                    "— needs block_threshold in between. Skipped automatic insertion; "
                    "manual edit recommended."
                )

    return pj, patches


def fix_recipe_list(pj: dict) -> tuple[dict, list[str]]:
    """Bug C: alert needs an upstream logic node. Insert block_threshold(>=1) on row count.

    Rather than mutate edges (risky), we replace alert with threshold+alert pair
    when the pattern matches. For MVP we document the skeleton — user should
    manually rebuild these 5 pipelines in the Builder UI.
    """
    patches: list[str] = []
    nodes = pj.get("nodes") or []
    node_blocks = {n.get("id"): n.get("block_id") for n in nodes}

    has_alert = "block_alert" in node_blocks.values()
    has_logic = any(b in node_blocks.values()
                    for b in ("block_threshold", "block_count_rows", "block_consecutive_rule",
                              "block_weco_rules", "block_any_trigger"))
    if has_alert and not has_logic:
        patches.append(
            "⚠  RECIPE template has block_alert without any logic block upstream. "
            "block_alert requires upstream `triggered` signal. Manual edit needed "
            "(add block_count_rows → block_threshold(>=1) between process_history and alert)."
        )
    return pj, patches


def run(dsn: str, apply: bool) -> int:
    total = fixed = flagged = 0
    errors: list[str] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, pipeline_json::text FROM pb_pipelines "
                "WHERE name LIKE '[DR-%' ORDER BY id;"
            )
            rows = cur.fetchall()
            for pid, name, raw in rows:
                total += 1
                try:
                    pj = json.loads(raw)
                except json.JSONDecodeError as e:
                    errors.append(f"  ⚠ {pid} {name}: bad JSON — {e}")
                    continue

                if _is_spc_trend(name):
                    pj, patches = fix_spc_trend(pj)
                elif _is_apc_list(name):
                    pj, patches = fix_apc_list(pj)
                elif _is_recipe_list(name):
                    pj, patches = fix_recipe_list(pj)
                else:
                    patches = []

                if not patches:
                    print(f"  {pid:>3} {name[:60]}  — no patches needed / matched")
                    continue

                mark = "PATCH" if apply else "DRY"
                print(f"  [{mark}] {pid:>3} {name[:60]}:")
                for p in patches:
                    print(f"        - {p}")
                    if p.startswith("⚠"):
                        flagged += 1
                    else:
                        fixed += 1

                if apply:
                    new_raw = json.dumps(pj, ensure_ascii=False)
                    cur.execute(
                        "UPDATE pb_pipelines SET pipeline_json = %s, updated_at = NOW() WHERE id = %s",
                        (new_raw, pid),
                    )
        if apply:
            conn.commit()

    print()
    print(f"Total DR pipelines: {total}")
    print(f"Auto-fixed rewrites: {fixed}")
    print(f"Flagged for manual edit: {flagged}")
    if errors:
        print("Errors:")
        print("\n".join(errors))
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True, help="PG DSN e.g. postgresql://aiops:pw@localhost/aiops_db")
    parser.add_argument("--apply", action="store_true", help="commit; default dry-run")
    args = parser.parse_args()
    return run(args.dsn, args.apply)


if __name__ == "__main__":
    sys.exit(main())
