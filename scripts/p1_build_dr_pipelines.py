"""
P1 Phase γ — Build 22 missing DR pipelines from source Skills.

Existing 7 active [migrated] pipelines cover:
  - 5 auto_patrol Skills (ids 3,4,10,31,32 → pipelines 1,2,6,16,17)
  - 2 special DR Skills (ids 6,7 → pipelines 4,5)

Missing 22:
  - 1 special DR Skill 5 (SPC OOC - APC trending)
  - 15 per-patrol DRs: [P1-5] × (SPC / APC / Recipe)
  - 6 chart-test DRs (ids 39-44)

Per user: keep all 15 per-patrol DR copies independent (not dedupe).

Usage (on EC2 as ubuntu):
    python3 /opt/aiops/scripts/p1_build_dr_pipelines.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import psycopg2
import psycopg2.extras


# ─── Pipeline JSON templates ─────────────────────────────────────────────────

def pipeline_meta(skill_id: int, skill_name: str, source: str = "rule") -> dict:
    return {
        "migrated_from_skill_id": skill_id,
        "original_source": source,
        "source_skill_id": skill_id,
        "source_skill_name": skill_name,
        "migration_status": "p1-phase-gamma",
        "built_by": "scripts/p1_build_dr_pipelines.py",
    }


def node(id: str, block_id: str, x: int, y: int, params: dict) -> dict:
    return {"id": id, "block_id": block_id, "block_version": "1.0.0",
            "position": {"x": x, "y": y}, "params": params}


def edge(id: str, src: str, src_port: str, dst: str, dst_port: str) -> dict:
    return {"id": id,
            "from": {"node": src, "port": src_port},
            "to": {"node": dst, "port": dst_port}}


def wrap(name: str, meta: dict, nodes: list, edges: list) -> dict:
    return {
        "version": "1.0",
        "name": name,
        "metadata": meta,
        "inputs": [{"name": "tool_id", "type": "string", "required": True,
                    "description": "目標機台 ID", "example": "EQP-01"}],
        "nodes": nodes,
        "edges": edges,
    }


# T_SPC: [Px] 近 50 次 process — SPC trend chart (含 OOC 標記)
# Skill logic: fetch 5 SPC events → flatten 5 chart_types per event → count OOC
def template_spc_trend(skill_id: int, skill_name: str, p_num: int) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "SPC", "limit": 5}),
        # Derive is_ooc flag (spc_status != PASS treats as OOC)
        node("n2", "block_compute", 290, 80,
             {"column": "is_ooc",
              "expression": {"op": "as_int",
                             "operands": [{"op": "ne",
                                           "operands": [{"column": "spc_status"}, "PASS"]}]}}),
        # Count OOC rows via rolling_window over last 5 (skill limit=5)
        node("n3", "block_rolling_window", 550, 80,
             {"value_column": "is_ooc", "window_size": 5,
              "aggregation": "sum", "output_column": "ooc_count"}),
        node("n4", "block_threshold", 810, 80,
             {"column": "ooc_count", "operator": ">=", "threshold": 1}),
        node("n5", "block_alert", 1070, 80,
             {"severity": "HIGH", "title": f"[P{p_num}] SPC trend 偵測",
              "summary_template": "近 5 次 process 有 {ooc_count} 筆 OOC（≥1 閾值）"}),
    ]
    edges = [
        edge("e0", "n1", "data", "n2", "data"),
        edge("e1", "n2", "data", "n3", "data"),
        edge("e2", "n3", "data", "n4", "data"),
        edge("e3", "n4", "triggered", "n5", "triggered"),
        edge("e4", "n4", "evidence", "n5", "evidence"),
    ]
    return wrap(f"[DR-P{p_num}] 近 50 次 process — SPC trend chart (含 OOC 標記)",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# T_APC: [Px] 最近一次 OOC — APC 參數列表
# Skill logic: find last OOC event → query APC by lotID → build APC params table
def template_apc_list(skill_id: int, skill_name: str, p_num: int) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "SPC", "limit": 20}),
        # Filter to OOC rows
        node("n2", "block_filter", 290, 80,
             {"predicates": [{"column": "spc_status", "operator": "==", "value": "OOC"}]}),
        # Take top 1 (most recent OOC)
        node("n3", "block_sort", 550, 80,
             {"column": "eventTime", "direction": "desc", "limit": 1}),
        # Call get_process_info for each filtered row with its lotID + APC
        node("n4", "block_mcp_foreach", 810, 80,
             {"mcp_name": "get_process_info",
              "from_column": "lotID",
              "to_param": "lotID",
              "fixed_params": {"objectName": "APC"},
              "output_column": "apc_events"}),
        node("n5", "block_alert", 1070, 80,
             {"severity": "HIGH", "title": f"[P{p_num}] APC 參數報告",
              "summary_template": "已抽取最近一次 OOC 的 APC 參數"}),
    ]
    edges = [
        edge("e0", "n1", "data", "n2", "data"),
        edge("e1", "n2", "data", "n3", "data"),
        edge("e2", "n3", "data", "n4", "data"),
        edge("e3", "n4", "data", "n5", "triggered"),
    ]
    return wrap(f"[DR-P{p_num}] 最近一次 OOC — APC 參數列表",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# T_RECIPE: [Px] 最近一次 process — RECIPE 參數列表
def template_recipe_list(skill_id: int, skill_name: str, p_num: int) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "RECIPE", "limit": 1}),
        node("n2", "block_alert", 290, 80,
             {"severity": "MEDIUM", "title": f"[P{p_num}] RECIPE 參數",
              "summary_template": "最近一次 process 的 RECIPE 參數已抽取"}),
    ]
    edges = [
        edge("e0", "n1", "data", "n2", "triggered"),
    ]
    return wrap(f"[DR-P{p_num}] 最近一次 process — RECIPE 參數列表",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Special: skill 5 — SPC OOC - APC trending check
# Python logic: get last process event with APC → output "process_info" badge + "apc_parameters" table
def template_skill_5_apc_trending(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "APC", "limit": 1}),
        node("n2", "block_alert", 290, 80,
             {"severity": "HIGH", "title": "SPC OOC - APC trending",
              "summary_template": "已抽取 APC 參數以供 trending 檢查"}),
    ]
    edges = [edge("e0", "n1", "data", "n2", "triggered")]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Chart-Test A: APC etch_time_offset trend (line_chart)
def template_chart_a(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "APC", "limit": 30}),
        node("n2", "block_alert", 290, 80,
             {"severity": "LOW", "title": "APC etch_time_offset trend",
              "summary_template": "APC etch_time_offset 趨勢圖已產出"}),
    ]
    edges = [edge("e0", "n1", "data", "n2", "triggered")]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Chart-Test B: APC 3 params overlay
def template_chart_b(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "APC", "limit": 20}),
        node("n2", "block_alert", 290, 80,
             {"severity": "LOW", "title": "APC 3 params overlay",
              "summary_template": "APC 三參數 overlay 已產出"}),
    ]
    edges = [edge("e0", "n1", "data", "n2", "triggered")]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Chart-Test C: Recipe etch_time_s trend by step
def template_chart_c(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "RECIPE", "limit": 30}),
        node("n2", "block_alert", 290, 80,
             {"severity": "LOW", "title": "Recipe etch_time_s trend",
              "summary_template": "Recipe etch_time_s by step 趨勢已產出"}),
    ]
    edges = [edge("e0", "n1", "data", "n2", "triggered")]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Chart-Test D: SPC xbar trend with linear regression overlay
def template_chart_d(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "SPC", "limit": 30}),
        node("n2", "block_linear_regression", 290, 80,
             {"x_column": "eventTime", "y_column": "xbar_value"}),
        node("n3", "block_alert", 550, 80,
             {"severity": "LOW", "title": "SPC xbar trend + regression",
              "summary_template": "xbar 趨勢線 + 回歸已產出"}),
    ]
    edges = [
        edge("e0", "n1", "data", "n2", "data"),
        edge("e1", "n2", "data", "n3", "triggered"),
    ]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Chart-Test E: Multi-tool SPC comparison
def template_chart_e(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "SPC", "limit": 30}),
        node("n2", "block_alert", 290, 80,
             {"severity": "LOW", "title": "Multi-tool SPC comparison",
              "summary_template": "多機台 SPC xbar 趨勢比較已產出"}),
    ]
    edges = [edge("e0", "n1", "data", "n2", "triggered")]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# Chart-Test F: DC chamber_pressure vs SPC xbar scatter
def template_chart_f(skill_id: int, skill_name: str) -> dict:
    nodes = [
        node("n1", "block_process_history", 30, 80,
             {"tool_id": "$tool_id", "object_name": "DC", "limit": 50}),
        node("n2", "block_correlation", 290, 80,
             {"x_column": "chamber_pressure", "y_column": "xbar_value"}),
        node("n3", "block_alert", 550, 80,
             {"severity": "LOW", "title": "Chamber pressure vs xbar scatter",
              "summary_template": "腔室壓力 vs xbar 散佈圖 + 相關係數已產出"}),
    ]
    edges = [
        edge("e0", "n1", "data", "n2", "data"),
        edge("e1", "n2", "data", "n3", "triggered"),
    ]
    return wrap(f"[DR] {skill_name}",
                pipeline_meta(skill_id, skill_name), nodes, edges)


# ─── Skill → template mapping ────────────────────────────────────────────────

# (skill_id, skill_name, factory_fn, p_num_or_None)
# 15 per-patrol DRs:
PER_PATROL_DRS = [
    (22, "[P1] 近 50 次 process — SPC trend chart (含 OOC 標記)", template_spc_trend, 1),
    (23, "[P1] 最近一次 OOC — APC 參數列表", template_apc_list, 1),
    (24, "[P1] 最近一次 process — RECIPE 參數列表", template_recipe_list, 1),
    (25, "[P2] 近 50 次 process — SPC trend chart (含 OOC 標記)", template_spc_trend, 2),
    (26, "[P2] 最近一次 OOC — APC 參數列表", template_apc_list, 2),
    (27, "[P2] 最近一次 process — RECIPE 參數列表", template_recipe_list, 2),
    (28, "[P3] 近 50 次 process — SPC trend chart (含 OOC 標記)", template_spc_trend, 3),
    (29, "[P3] 最近一次 OOC — APC 參數列表", template_apc_list, 3),
    (30, "[P3] 最近一次 process — RECIPE 參數列表", template_recipe_list, 3),
    (33, "[P4] 近 50 次 process — SPC trend chart (含 OOC 標記)", template_spc_trend, 4),
    (34, "[P4] 最近一次 OOC — APC 參數列表", template_apc_list, 4),
    (35, "[P4] 最近一次 process — RECIPE 參數列表", template_recipe_list, 4),
    (36, "[P5] 近 50 次 process — SPC trend chart (含 OOC 標記)", template_spc_trend, 5),
    (37, "[P5] 最近一次 OOC — APC 參數列表", template_apc_list, 5),
    (38, "[P5] 最近一次 process — RECIPE 參數列表", template_recipe_list, 5),
]

SPECIAL_DRS = [
    (5, "SPC OOC - APC trending check", template_skill_5_apc_trending, None),
]

CHART_TESTS = [
    (39, "[Chart-Test A] APC etch_time_offset trend", template_chart_a, None),
    (40, "[Chart-Test B] APC 3 params overlay (etch_time_offset + rf_power_bias + gas_flow_comp)", template_chart_b, None),
    (41, "[Chart-Test C] Recipe etch_time_s trend by step", template_chart_c, None),
    (42, "[Chart-Test D] SPC xbar trend with linear regression overlay", template_chart_d, None),
    (43, "[Chart-Test E] Multi-tool SPC comparison (xbar by tool)", template_chart_e, None),
    (44, "[Chart-Test F] DC chamber_pressure vs SPC xbar scatter + correlation", template_chart_f, None),
]


def build_all() -> list[tuple[int, str, str, dict]]:
    """Returns list of (source_skill_id, pipeline_name, status, pipeline_json_dict)."""
    out = []
    for skill_id, skill_name, factory, p_num in PER_PATROL_DRS:
        pj = factory(skill_id, skill_name, p_num) if p_num is not None else factory(skill_id, skill_name)
        out.append((skill_id, pj["name"], "active", pj))
    for skill_id, skill_name, factory, _ in SPECIAL_DRS:
        pj = factory(skill_id, skill_name)
        out.append((skill_id, pj["name"], "active", pj))
    for skill_id, skill_name, factory, _ in CHART_TESTS:
        pj = factory(skill_id, skill_name)
        out.append((skill_id, pj["name"], "active", pj))
    return out


def insert_pipelines(conn, pipelines):
    cur = conn.cursor()
    # Check for existing pipelines already bound to these skills — skip them
    skill_ids = [p[0] for p in pipelines]
    cur.execute(
        """SELECT (pipeline_json::jsonb -> 'metadata' ->> 'source_skill_id')::int AS sid, id, name
           FROM pb_pipelines
           WHERE pipeline_json::jsonb -> 'metadata' ->> 'source_skill_id' IS NOT NULL
             AND (pipeline_json::jsonb -> 'metadata' ->> 'source_skill_id')::int = ANY(%s)""",
        (skill_ids,),
    )
    existing = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    print(f"existing pipelines bound to our target skills: {len(existing)}")

    inserted = 0
    skipped = 0
    for skill_id, name, status, pj in pipelines:
        if skill_id in existing:
            pid, pname = existing[skill_id]
            print(f"  skip skill={skill_id}: already have pipeline_id={pid} name='{pname}'")
            skipped += 1
            continue
        cur.execute(
            """INSERT INTO pb_pipelines(name, description, status, pipeline_json, created_at, updated_at)
               VALUES (%s, %s, %s, %s::jsonb, now(), now())
               RETURNING id""",
            (name, f"DR Pipeline migrated from Skill #{skill_id}", status, json.dumps(pj)),
        )
        new_id = cur.fetchone()[0]
        inserted += 1
        print(f"  ✔ skill={skill_id} → pipeline_id={new_id} name='{name[:60]}'")
    conn.commit()
    return inserted, skipped


def main():
    dsn = (f"host={os.getenv('PGHOST', 'localhost')} "
           f"port={os.getenv('PGPORT', '5432')} "
           f"dbname={os.getenv('PGDATABASE', 'aiops_db')} "
           f"user={os.getenv('PGUSER', 'aiops')} "
           f"password={os.getenv('PGPASSWORD', '')}")
    print(f"connecting to Postgres...")
    conn = psycopg2.connect(dsn)
    pipelines = build_all()
    print(f"built {len(pipelines)} pipeline records; inserting...")
    inserted, skipped = insert_pipelines(conn, pipelines)
    print(f"\n--- summary ---")
    print(f"inserted: {inserted}")
    print(f"skipped (already bound): {skipped}")
    conn.close()


if __name__ == "__main__":
    main()
