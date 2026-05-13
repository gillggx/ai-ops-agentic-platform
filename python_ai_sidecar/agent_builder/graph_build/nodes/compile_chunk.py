"""compile_chunk_node — v16 Phase 2 of macro+chunk architecture.

Takes 1 macro step at a time and translates it to 1-3 concrete ops
(add_node / connect / set_param). Append to state.plan; the existing
dispatch_op + call_tool loop walks them. After all ops for THIS step
have executed, routing brings us back here for the NEXT macro step.

Why this scales better than 1-shot plan_node:
- LLM sees ONLY 1 step at a time → input scope ~10x smaller
- Block catalog filtered to just the candidate + neighbors (~5 blocks)
  rather than all 52 (~5k tokens vs ~55k)
- Errors localized: if step 3's compile fails, we retry step 3, don't
  touch steps 1-2 (which already ran successfully)
- Upstream state (real cols + sample) feeds in, so the LLM doesn't
  have to "guess" what upstream produces

Output: appends 1-3 ops to state.plan. validate_chunk runs after to
catch structural errors. On failure, compile_attempts[step] increments;
max 2 retries before falling back to reflect_plan / failing the build.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


MAX_COMPILE_ATTEMPTS = 2
# How many "neighbor" blocks to include in the LLM prompt context
# alongside the candidate block_id. Picks blocks in the same category.
N_NEIGHBOR_BLOCKS = 4


_SYSTEM = """你是 pipeline op-compiler。給你 1 個 macro step 的描述，你產出 1-5 個 ops 來實作它。

每個 op 是下面 5 種之一:
  - add_node     (帶 block_id, block_version="1.0.0", node_id, params)
  - set_param    (改 existing node 的 1 個 param)
  - connect      (接 2 個 node 的 port: src_id, src_port, dst_id, dst_port)
  - run_preview  (debug 用，通常不必)
  - remove_node  (刪 existing node)

你會看到:
  1. 這個 macro step 的描述 + expected_kind + candidate_block hint
  2. 上游已建好的 nodes (含 block_id + 真實 output cols；nested 結構會標出 shape hint)
  3. 候選 blocks (含完整 description + param_schema — block 的事實只從這裡來)
  4. 整個 macro plan 的脈絡 (前後 steps 都做什麼)

嚴格規則 (違反 → op 會被擋下):

1. **不重複 add_node**
   - UPSTREAM TRACE 列出的 logical id (n1, n2, ...) 都已經在 canvas 上，**不要再 add 第二次**
   - 如果某 macro step 看起來需要的 block 已經在 canvas (block_id 一樣)，**不 add，改用 set_param 改它的參數** 或直接 connect
   - 新加 node 的 logical id 必須是接續編號 (canvas 最大 + 1)

2. **column ref 嚴格從 UPSTREAM TRACE 取**
   - 如果 op 的 param 是 column 名 (filter.column, sort.columns, select.fields, chart.x/y...)，**這個名字必須出現在 UPSTREAM TRACE 任一個 upstream node 的 cols 裡**
   - 如果你想用的 column 是某 nested col 的 leaf（UPSTREAM TRACE 有秀「list[{...}]」或「dict{...}」shape hint），**這個 step 要先補一個解 nested 的 block (例如 unnest)**，再做 filter / sort / chart
   - 不確定欄位該叫什麼 → 看 RELEVANT BLOCKS 區段該 block 的 description；不要憑想像

3. **不要 remove 上游 node** — 上游已穩，這 step 只負責接續

4. **大部分 step 是 1 add_node + 1 connect**；但如果 macro step text 描述 2 件事（例如「展開 nested 並過濾」）或上游需要先解 nested，**emit 多組 (add_node + connect) 鏈在一起**，最多 5 ops

5. **block_id 必須在 RELEVANT BLOCKS 區段裡**，不要自己合成新名 (系統會 reject)

只輸出 JSON:
{
  "ops": [
    {"type": "add_node", "block_id": "...", "block_version": "1.0.0",
     "node_id": "n3", "params": {...}},
    {"type": "connect", "src_id": "n2", "src_port": "data",
     "dst_id": "n3", "dst_port": "data"}
  ],
  "reason": "<1 句話為什麼這樣編>"
}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


# Fallback map for column-ref params per block — used when the block's
# param_schema doesn't carry `x-column-source` markers. Prefer the schema-
# driven path in _get_column_ref_params; this is just a safety net for
# older block specs.
_COLUMN_REF_PARAMS_FALLBACK = {
    "block_filter": ["column"],
    "block_sort": ["columns"],
    "block_select": ["fields"],
    "block_groupby_agg": ["group_by", "agg_column"],
    # Standard chart blocks — x/y are column refs
    "block_line_chart": ["x", "y"],
    "block_bar_chart": ["x", "y"],
    "block_scatter": ["x", "y"],
    "block_area_chart": ["x", "y"],
    "block_pie_chart": ["category", "value"],
    # SPC / statistical chart blocks — value_column is the col to analyse
    "block_ewma_cusum": ["value_column"],
    "block_box_plot": ["x", "y", "group_by"],
    "block_probability_plot": ["value_column"],
    "block_xbar_r": ["value_column", "subgroup_column"],
    "block_imr": ["value_column"],
    "block_pareto": ["category_column", "value_column"],
    "block_cpk": ["value_column", "group_by"],
    "block_distribution": ["value_column"],
    "block_heatmap": ["x", "y", "value_column"],
    # Transform / utility
    "block_data_view": ["columns"],
    "block_threshold": ["column"],
    "block_consecutive_rule": ["column"],
    "block_linear_regression": ["x_column", "y_column"],
    "block_unnest": ["column"],
    "block_pluck": ["column"],
    "block_step_check": ["column"],
}


def _get_column_ref_params(block_id: str, catalog: dict) -> list[str]:
    """Return the column-reference param names for a block.

    Schema-driven: walk param_schema.properties and collect any prop whose
    metadata has `x-column-source` (set by seed.py). Falls back to the
    static map for blocks whose schema doesn't carry the marker yet.
    """
    spec = next((s for (n, _v), s in catalog.items() if n == block_id), None)
    if not spec:
        return _COLUMN_REF_PARAMS_FALLBACK.get(block_id, [])
    schema = spec.get("param_schema") or {}
    props = schema.get("properties") or {}
    names: list[str] = []
    for pname, p in props.items():
        if not isinstance(p, dict):
            continue
        if p.get("x-column-source") or p.get("x-column-ref"):
            names.append(pname)
    if names:
        return names
    return _COLUMN_REF_PARAMS_FALLBACK.get(block_id, [])


def _collect_upstream_cols(plan: list[dict], exec_trace: dict) -> set[str]:
    """Union of cols observed in exec_trace for any logical id in plan.

    Used by _validate_column_refs as the "allowed columns" set. Each
    block's preview adds a snapshot keyed by logical id; we union them
    so a column emitted by ANY upstream node is considered valid.

    Also derives leaves from the sample row when a top-level column
    holds a nested dict / list-of-dicts (e.g. cols=['spc_charts'],
    sample={spc_charts:[{name,value,...}]} → also add 'spc_charts[].name'
    etc.). Without this, preview snapshots that only report top-level
    df.columns miss the nested structure entirely and the validator's
    leaf-detection has nothing to work with.
    """
    cols: set[str] = set()
    for op in plan:
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id")
        snap = exec_trace.get(lid) or {}
        for c in snap.get("cols") or []:
            cols.add(c)
            if "." in c:
                cols.add(c.split(".", 1)[0])
            if "[]" in c:
                cols.add(c.split("[]", 1)[0])
        # Mine sample for nested leaves
        sample = snap.get("sample")
        if isinstance(sample, dict):
            for k, v in sample.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    for leaf in v[0].keys():
                        cols.add(f"{k}[].{leaf}")
                elif isinstance(v, dict):
                    for leaf in v.keys():
                        cols.add(f"{k}.{leaf}")
    return cols


def _block_output_types(block_id: str, catalog: dict) -> dict[str, str]:
    """Return {port: type} for a block's output_schema."""
    for (name, _v), spec in catalog.items():
        if name == block_id:
            out = {}
            for port in (spec.get("output_schema") or []):
                if isinstance(port, dict):
                    out[port.get("port", "")] = port.get("type", "")
            return out
    return {}


def _block_input_types(block_id: str, catalog: dict) -> dict[str, str]:
    for (name, _v), spec in catalog.items():
        if name == block_id:
            out = {}
            for port in (spec.get("input_schema") or []):
                if isinstance(port, dict):
                    out[port.get("port", "")] = port.get("type", "")
            return out
    return {}


def _block_id_of_logical(lid: str, plan: list[dict], new_ops: list[dict]) -> str | None:
    """Find block_id for a logical node id (n1, n2, ...) by scanning add_node ops."""
    for op in list(new_ops) + list(plan):
        if op.get("type") == "add_node" and op.get("node_id") == lid:
            return op.get("block_id")
    return None


def _auto_rewire_chart_chains(
    new_ops: list[dict[str, Any]],
    plan: list[dict[str, Any]],
    catalog: dict,
) -> tuple[list[dict[str, Any]], list[str]]:
    """When a new connect's src is a chart-output (chart_spec / dict / bool)
    node but dst expects dataframe, rewire src to the latest dataframe-
    outputting node in plan. Chart blocks are terminal — chaining one chart
    into another's dataframe input is a structural error the LLM does
    repeatedly when a macro plan lists multiple analyses sequentially.

    Returns (rewritten_ops, notes).
    """
    if not new_ops:
        return new_ops, []

    # Build the list of dataframe-outputting nodes in execution order
    # (plan first, then new_ops). The "latest dataframe" is the closest
    # such node before any chart node we just added.
    dataframe_lids: list[str] = []
    for op in list(plan) + list(new_ops):
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id")
        block_id = op.get("block_id")
        if not lid or not block_id:
            continue
        out_types = _block_output_types(block_id, catalog)
        if "data" in out_types and out_types["data"] == "dataframe":
            dataframe_lids.append(lid)

    if not dataframe_lids:
        return new_ops, []

    notes: list[str] = []
    rewritten: list[dict[str, Any]] = []
    for op in new_ops:
        if op.get("type") != "connect":
            rewritten.append(op)
            continue
        src_lid = op.get("src_id") or ""
        dst_lid = op.get("dst_id") or ""
        src_block = _block_id_of_logical(src_lid, plan, new_ops)
        dst_block = _block_id_of_logical(dst_lid, plan, new_ops)
        if not src_block or not dst_block:
            rewritten.append(op)
            continue
        src_out = _block_output_types(src_block, catalog)
        dst_in = _block_input_types(dst_block, catalog)
        src_port = op.get("src_port") or "data"
        dst_port = op.get("dst_port") or "data"
        src_type = src_out.get(src_port)
        dst_type = dst_in.get(dst_port)
        # Source can't supply a dataframe on the requested port when EITHER
        # the named port doesn't exist on src OR exists but is non-dataframe
        # (chart_spec/dict/bool). Both mean "this is a chart→data chaining
        # mistake; rewire to the nearest upstream dataframe-emitting node".
        src_has_dataframe = any(t == "dataframe" for t in src_out.values())
        src_supplies_dataframe_on_port = src_type == "dataframe"
        if dst_type == "dataframe" and not src_supplies_dataframe_on_port and not src_has_dataframe:
            # Find latest dataframe lid that comes BEFORE the dst in plan order
            # Simplest: use the latest dataframe lid that's not the dst itself
            candidates = [lid for lid in dataframe_lids if lid != dst_lid]
            if candidates:
                new_src = candidates[-1]
                rewritten.append({
                    **op,
                    "src_id": new_src,
                    "src_port": "data",
                })
                notes.append(
                    f"auto-rewired connect dst={dst_lid}({dst_block}): "
                    f"src {src_lid}({src_block}, {src_type}) → {new_src} (dataframe)"
                )
                continue
        rewritten.append(op)

    return rewritten, notes


def _autocorrect_filter_values(
    new_ops: list[dict[str, Any]],
    plan: list[dict[str, Any]],
    exec_trace: dict | None,
) -> list[str]:
    """When LLM emits block_filter with column='<leaf>' value='<shorthand>'
    but the actual leaf values in upstream sample don't include the literal
    (e.g. value='xbar' against ['xbar_chart','r_chart',...]), auto-correct
    the value to the closest match.

    Common pattern: user prompt says "xbar 趨勢" / "spc_xbar_chart_value",
    LLM literally uses 'xbar' as filter value. Actual data has chart keys
    with full names ('xbar_chart'). Filter returns 0 rows, downstream
    Cpk/EWMA fail with n=0 samples.

    Mutates new_ops in-place. Returns notes describing each correction.
    """
    notes: list[str] = []
    if not exec_trace:
        return notes

    # Build a {col_name → set of observed values} index from upstream samples.
    # We only look at list-of-dict columns (the nested arrays unnest will
    # expand). Each dict's keys + values form the lookup set.
    leaf_values: dict[str, set[str]] = {}
    for op in plan:
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id")
        snap = exec_trace.get(lid) or {}
        sample = snap.get("sample")
        if not isinstance(sample, dict):
            continue
        for k, v in sample.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                for entry in v:
                    if not isinstance(entry, dict):
                        continue
                    for leaf_key, leaf_val in entry.items():
                        if isinstance(leaf_val, str):
                            leaf_values.setdefault(leaf_key, set()).add(leaf_val)

    if not leaf_values:
        return notes

    for op in new_ops:
        if op.get("type") != "add_node":
            continue
        if op.get("block_id") != "block_filter":
            continue
        params = op.get("params") or {}
        col = params.get("column")
        val = params.get("value")
        if not isinstance(col, str) or not isinstance(val, str):
            continue
        observed = leaf_values.get(col)
        if not observed or val in observed:
            continue
        # Find observed value that contains `val` as substring (or vice versa)
        # — exactly the case 'xbar' vs 'xbar_chart'.
        v_low = val.lower()
        matches = [obs for obs in observed if v_low in obs.lower() or obs.lower() in v_low]
        if len(matches) == 1:
            params["value"] = matches[0]
            notes.append(
                f"auto-corrected block_filter (node {op.get('node_id')}): "
                f"value '{val}' → '{matches[0]}' (matched from upstream sample's "
                f"'{col}' values: {sorted(observed)[:5]})"
            )
    return notes


def _validate_required_params(
    new_ops: list[dict[str, Any]],
    catalog: dict,
) -> list[str]:
    """Catch missing-required-param violations at compile_chunk time
    so we retry with feedback instead of letting the build run all the
    way to finalize's C6_PARAM_SCHEMA check.

    For each add_node, look up the block's param_schema.required list
    and verify every required key is present in params (None values
    were already stripped by execute._build_tool_args, but compile_chunk
    sees raw LLM output here, so check 'is not None' too).
    """
    issues: list[str] = []
    for op in new_ops:
        if op.get("type") != "add_node":
            continue
        block_id = op.get("block_id") or ""
        spec = next((s for (n, _v), s in catalog.items() if n == block_id), None)
        if not spec:
            continue
        schema = spec.get("param_schema") or {}
        required = schema.get("required") or []
        params = op.get("params") or {}
        for req_key in required:
            val = params.get(req_key)
            if val is None or (isinstance(val, str) and not val.strip()):
                issues.append(
                    f"{block_id}.{req_key} is required but missing/null "
                    f"(node {op.get('node_id')})"
                )
    return issues


def _find_unnest_block(catalog: dict) -> str | None:
    """Locate the catalog's list→rows explode block by capability, not by
    name. Heuristic: a block whose param_schema accepts a single `column`
    parameter, outputs a dataframe, AND has 'unnest' / 'explode' /
    'flatten' in its name or description.

    Returns block_id (e.g. 'block_unnest') or None if no match.
    """
    for (name, _v), spec in catalog.items():
        nlc = name.lower()
        if any(kw in nlc for kw in ("unnest", "explode", "flatten")):
            params = (spec.get("param_schema") or {}).get("properties") or {}
            if "column" in params:
                return name
        # Fallback: scan description for the action verb
        desc = (spec.get("description") or "").lower()
        if "unnest" in desc.split("\n", 1)[0] or "explode" in desc.split("\n", 1)[0]:
            params = (spec.get("param_schema") or {}).get("properties") or {}
            if "column" in params:
                return name
    return None


def _auto_insert_unnest(
    new_ops: list[dict[str, Any]],
    plan: list[dict[str, Any]],
    upstream_cols: set[str],
    catalog: dict,
    exec_trace: dict | None = None,
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """If any new add_node references a nested leaf, prepend an unnest
    add_node + connect to flatten the parent. Re-wire the offending op's
    inbound connect to come from the unnest node instead of the original
    upstream.

    Returns (rewritten_ops, applied_notes, added_leaves) where added_leaves
    are the column names that would become available after the inserted
    unnest runs — caller merges these into upstream_cols so the col-ref
    validator sees the new node's flat output cols.
    """
    if not upstream_cols:
        return new_ops, [], set()

    # Collect existing logical IDs to compute next-free ones for the inserts
    existing_lids: set[str] = set()
    max_n = 0
    for op in (plan + new_ops):
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id") or ""
        existing_lids.add(lid)
        if lid.startswith("n") and lid[1:].isdigit():
            max_n = max(max_n, int(lid[1:]))

    def next_lid() -> str:
        nonlocal max_n
        max_n += 1
        while f"n{max_n}" in existing_lids:
            max_n += 1
        existing_lids.add(f"n{max_n}")
        return f"n{max_n}"

    unnest_block = _find_unnest_block(catalog)
    if not unnest_block:
        return new_ops, [], set()  # no unnest-capable block in catalog → can't autofix

    # Collect parents that are ALREADY being unnested in this step or
    # earlier in the plan, so we don't double-insert. Look at any
    # add_node whose block_id matches the unnest block AND whose
    # params.column points to the same parent col.
    already_unnested_parents: set[str] = set()
    for op in (list(plan) + list(new_ops)):
        if op.get("type") != "add_node":
            continue
        if op.get("block_id") == unnest_block:
            col = (op.get("params") or {}).get("column")
            if isinstance(col, str) and col:
                already_unnested_parents.add(col)

    notes: list[str] = []
    added_leaves: set[str] = set()
    rewritten: list[dict[str, Any]] = []
    # Map from old logical_id (the offending node) → unnest_id we inserted
    rewire: dict[str, str] = {}

    for op in new_ops:
        if op.get("type") == "add_node":
            block_id = op.get("block_id") or ""
            ref_params = _get_column_ref_params(block_id, catalog)
            params = op.get("params") or {}
            offending_parent: str | None = None
            for pname in ref_params:
                val = params.get(pname)
                candidates = val if isinstance(val, list) else [val]
                for cand in candidates:
                    if not isinstance(cand, str) or not cand or cand.startswith("$"):
                        continue
                    root = cand.split(".", 1)[0].split("[", 1)[0]
                    if cand in upstream_cols or root in upstream_cols:
                        continue
                    parent = _find_leaf_in_nested(cand, upstream_cols)
                    if parent:
                        offending_parent = parent
                        break
                if offending_parent:
                    break
            if offending_parent:
                # Skip if the parent is already being unnested elsewhere
                # (LLM emitted it in this same step, or it's already in
                # the plan). Just add the leaves to upstream_cols so the
                # downstream validator passes without inserting a dup.
                if offending_parent in already_unnested_parents:
                    notes.append(
                        f"skipped duplicate unnest of '{offending_parent}' for "
                        f"{op.get('node_id')} — already unnested upstream"
                    )
                    # Still mine the leaves so validator sees them
                    if exec_trace:
                        for plan_op in plan:
                            if plan_op.get("type") != "add_node":
                                continue
                            plid = plan_op.get("node_id")
                            snap = exec_trace.get(plid) or {}
                            sample = snap.get("sample")
                            if not isinstance(sample, dict):
                                continue
                            v = sample.get(offending_parent)
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                for leaf in v[0].keys():
                                    added_leaves.add(str(leaf))
                                break
                            if isinstance(v, dict):
                                for leaf in v.keys():
                                    added_leaves.add(str(leaf))
                                break
                    rewritten.append(op)
                    continue
                unnest_lid = next_lid()
                op_lid = op.get("node_id") or ""
                rewire[op_lid] = unnest_lid
                rewritten.append({
                    "type": "add_node",
                    "block_id": unnest_block,
                    "block_version": "1.0.0",
                    "node_id": unnest_lid,
                    "params": {"column": offending_parent},
                })
                notes.append(
                    f"auto-inserted {unnest_block}(column='{offending_parent}') "
                    f"as {unnest_lid} before {op_lid}"
                )
                # Track that we've now unnested this parent so subsequent
                # ops in the same new_ops loop don't double-insert.
                already_unnested_parents.add(offending_parent)
                # The inserted unnest will flatten `offending_parent`'s
                # list-of-dict elements; leaf keys become top-level cols
                # downstream. Mine the parent's actual leaves from
                # exec_trace's sample row so the validator post-this
                # auto-insert sees them as valid refs.
                if exec_trace:
                    for plan_op in plan:
                        if plan_op.get("type") != "add_node":
                            continue
                        plid = plan_op.get("node_id")
                        snap = exec_trace.get(plid) or {}
                        sample = snap.get("sample")
                        if not isinstance(sample, dict):
                            continue
                        v = sample.get(offending_parent)
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            for leaf in v[0].keys():
                                added_leaves.add(str(leaf))
                            break
                        if isinstance(v, dict):
                            for leaf in v.keys():
                                added_leaves.add(str(leaf))
                            break
        rewritten.append(op)

    if not rewire:
        # No new ops needed (e.g. all offending leaves were already
        # handled by an existing upstream unnest). Still return notes
        # + leaves so the caller knows the validator's upstream_cols
        # should include the leaves the existing unnest will produce.
        return new_ops, notes, added_leaves

    # Pass 2: re-wire connects whose dst_id is the offending op — insert
    # a connect from the original upstream src into the new unnest node,
    # then rewrite the original connect's src to the unnest's output.
    final_ops: list[dict[str, Any]] = []
    handled_dst: set[str] = set()
    for op in rewritten:
        if op.get("type") == "connect":
            dst = op.get("dst_id")
            if dst in rewire and dst not in handled_dst:
                unnest_lid = rewire[dst]
                # connect: original_src → unnest
                final_ops.append({
                    "type": "connect",
                    "src_id": op.get("src_id"),
                    "src_port": op.get("src_port") or "data",
                    "dst_id": unnest_lid,
                    "dst_port": "data",
                })
                # connect: unnest → original_dst
                final_ops.append({
                    "type": "connect",
                    "src_id": unnest_lid,
                    "src_port": "data",
                    "dst_id": dst,
                    "dst_port": op.get("dst_port") or "data",
                })
                handled_dst.add(dst)
                continue
        final_ops.append(op)

    return final_ops, notes, added_leaves


def _find_leaf_in_nested(cand: str, upstream_cols: set[str]) -> str | None:
    """If `cand` is a leaf of some nested upstream col (e.g. 'name' is a
    leaf of 'spc_charts[].name' or 'ooc_count' of 'spc_summary.ooc_count'),
    return the parent column to unnest. None if no match.
    """
    for upcol in upstream_cols:
        if upcol == cand:
            continue
        # 'spc_charts[].name' → leaf='name', parent='spc_charts'
        if "[]." in upcol:
            parent, leaf = upcol.split("[].", 1)
            if leaf == cand:
                return parent
        # 'spc_summary.ooc_count' → leaf='ooc_count', parent='spc_summary'
        if "." in upcol:
            parent, leaf = upcol.rsplit(".", 1)
            if leaf == cand:
                return parent
    return None


def _validate_column_refs(
    new_ops: list[dict[str, Any]],
    upstream_cols: set[str],
    catalog: dict | None = None,
) -> list[str]:
    """Check every new add_node's column-ref params against upstream_cols.
    Returns list of human-readable issues; empty if all refs are valid.

    Skips validation if upstream_cols is empty (first compile step has
    no upstream snapshots yet — source block's params are user-given).
    Also passes any string value starting with '$' (declared input ref)
    and any value not in our column-ref param map (free-form params).
    """
    if not upstream_cols:
        return []
    issues: list[str] = []
    for op in new_ops:
        if op.get("type") != "add_node":
            continue
        block_id = op.get("block_id") or ""
        ref_params = (
            _get_column_ref_params(block_id, catalog) if catalog
            else _COLUMN_REF_PARAMS_FALLBACK.get(block_id, [])
        )
        if not ref_params:
            continue
        params = op.get("params") or {}
        for pname in ref_params:
            val = params.get(pname)
            candidates = val if isinstance(val, list) else [val]
            for cand in candidates:
                if not isinstance(cand, str) or not cand:
                    continue
                if cand.startswith("$"):
                    continue
                # Allow dotted paths whose ROOT is a known col
                root = cand.split(".", 1)[0].split("[", 1)[0]
                if cand in upstream_cols or root in upstream_cols:
                    continue
                # Actionable feedback: is this the leaf of a nested col?
                parent = _find_leaf_in_nested(cand, upstream_cols)
                if parent:
                    issues.append(
                        f"{block_id}.{pname}='{cand}' is a leaf of nested upstream col — "
                        f"先用一個解 nested 的 step (例如 unnest / flatten) 把 '{parent}' "
                        f"展開，下游才能直接引用 '{cand}'"
                    )
                else:
                    issues.append(
                        f"{block_id}.{pname}='{cand}' not in upstream cols "
                        f"({sorted(upstream_cols)[:8]}…)"
                    )
    return issues


def _dedup_against_plan(
    new_ops: list[dict[str, Any]],
    existing_plan: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop add_node ops whose logical id already exists in plan, and
    drop connect ops that exactly duplicate an existing edge.

    Returns (kept_ops, dropped_reasons).
    """
    existing_logical_ids: set[str] = set()
    existing_edges: set[tuple] = set()
    for op in existing_plan:
        t = op.get("type")
        if t == "add_node":
            lid = op.get("node_id")
            if lid:
                existing_logical_ids.add(lid)
        elif t == "connect":
            existing_edges.add((
                op.get("src_id"), op.get("src_port"),
                op.get("dst_id"), op.get("dst_port"),
            ))

    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for op in new_ops:
        t = op.get("type")
        if t == "add_node":
            lid = op.get("node_id")
            if lid and lid in existing_logical_ids:
                dropped.append(f"add_node {lid} (logical id already on canvas)")
                continue
            if lid:
                existing_logical_ids.add(lid)
        elif t == "connect":
            edge = (
                op.get("src_id"), op.get("src_port"),
                op.get("dst_id"), op.get("dst_port"),
            )
            if edge in existing_edges:
                dropped.append(f"connect {edge[0]}->{edge[2]} (duplicate edge)")
                continue
            existing_edges.add(edge)
        kept.append(op)
    return kept, dropped


def _existing_nodes_summary(plan: list[dict], exec_trace: dict) -> str:
    """One-line per existing logical node with its block_id + observed cols
    + (when nested) a shape hint from the sample row so the compile LLM
    knows whether a top-level col is a list/dict and needs unnest.
    """
    lines: list[str] = []
    for op in plan:
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id") or "?"
        block = op.get("block_id") or "?"
        snap = exec_trace.get(lid) or {}
        cols = snap.get("cols") or []
        sample = snap.get("sample") if isinstance(snap.get("sample"), dict) else None
        if not cols:
            lines.append(f"  {lid} [{block}] (no preview yet)")
            continue
        cols_str = ", ".join(cols[:8])
        if len(cols) > 8:
            cols_str += f"...+{len(cols)-8}"
        lines.append(f"  {lid} [{block}] cols=[{cols_str}]")
        # Nested shape hints — surface list[dict] / dict cols so LLM
        # plans an unnest step before referencing leaves.
        if sample:
            nested_hints: list[str] = []
            for k, v in sample.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    leaf_keys = list(v[0].keys())[:6]
                    nested_hints.append(
                        f"'{k}' = list[{{ {', '.join(leaf_keys)} }}] "
                        f"(要引用 leaf 先 unnest '{k}')"
                    )
                elif isinstance(v, dict):
                    leaf_keys = list(v.keys())[:6]
                    nested_hints.append(
                        f"'{k}' = dict{{ {', '.join(leaf_keys)} }} "
                        f"(用 path '{k}.<leaf>' 引用)"
                    )
            for hint in nested_hints[:4]:
                lines.append(f"      ↳ {hint}")
    return "\n".join(lines) if lines else "  (no upstream nodes — this is the first step)"


def _format_relevant_blocks(catalog: dict, candidate_id: str) -> str:
    """Format the candidate block + a few neighbors (same category) with
    full description + param_schema."""
    if not candidate_id:
        # No candidate — show high-traffic blocks
        keys = [k for k in catalog if "process_history" in k[0] or "filter" in k[0]
                or "step_check" in k[0]]
        relevant = [(k, catalog[k]) for k in keys[:N_NEIGHBOR_BLOCKS]]
    else:
        candidate_spec = None
        category = None
        for (name, _ver), spec in catalog.items():
            if name == candidate_id:
                candidate_spec = spec
                category = spec.get("category")
                break
        relevant: list[tuple[tuple, dict]] = []
        if candidate_spec:
            relevant.append(((candidate_id, "1.0.0"), candidate_spec))
        # add same-category neighbors
        for (name, ver), spec in catalog.items():
            if name == candidate_id:
                continue
            if spec.get("category") == category:
                relevant.append(((name, ver), spec))
                if len(relevant) >= N_NEIGHBOR_BLOCKS + 1:
                    break

    out_lines: list[str] = []
    for (name, _ver), spec in relevant:
        out_lines.append(f"=== {name} (category={spec.get('category', '?')}) ===")
        desc = (spec.get("description") or "").strip()
        out_lines.append(desc[:1200])  # cap description
        try:
            schema_str = json.dumps(
                spec.get("param_schema") or {}, ensure_ascii=False, indent=2,
            )[:1500]
        except (TypeError, ValueError):
            schema_str = "(schema serialization failed)"
        out_lines.append(f"param_schema:\n{schema_str}")
        out_lines.append("")
    return "\n".join(out_lines)


async def compile_chunk_node(state: BuildGraphState) -> dict[str, Any]:
    """Compile the current macro step into ops + append to state.plan."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )

    macro_plan = state.get("macro_plan") or []
    idx = state.get("current_macro_step", 0)

    if idx >= len(macro_plan):
        logger.info("compile_chunk_node: idx %d >= macro_plan len %d, nothing to compile",
                    idx, len(macro_plan))
        return {}

    step = macro_plan[idx]
    step_key = f"step_{step.get('step_idx', idx + 1)}"
    attempts_map = dict(state.get("compile_attempts") or {})
    attempts = attempts_map.get(step_key, 0) + 1
    attempts_map[step_key] = attempts

    if attempts > MAX_COMPILE_ATTEMPTS:
        logger.warning(
            "compile_chunk_node: step %s exceeded %d attempts — failing build",
            step_key, MAX_COMPILE_ATTEMPTS,
        )
        return {
            "compile_attempts": attempts_map,
            "status": "failed",
            "summary": f"Macro step {step_key} failed to compile after {MAX_COMPILE_ATTEMPTS} attempts.",
            "sse_events": [_event("compile_chunk_failed", {
                "step_idx": step.get("step_idx"),
                "attempts": attempts,
            })],
        }

    registry = SeedlessBlockRegistry()
    registry.load()

    candidate = step.get("candidate_block", "")
    relevant_blocks = _format_relevant_blocks(registry.catalog, candidate)
    existing_nodes = _existing_nodes_summary(state.get("plan") or [], state.get("exec_trace") or {})

    # Pull macro context: this step + neighbors (prev + next 1 each)
    context_lines: list[str] = []
    for i, s in enumerate(macro_plan):
        marker = " ← (你現在要編這個)" if i == idx else ""
        context_lines.append(f"  Step {s['step_idx']}: {s['text']}{marker}")

    declared_inputs = (state.get("base_pipeline") or {}).get("inputs") or []
    inputs_section = ""
    if declared_inputs:
        names = [inp.get("name") for inp in declared_inputs if isinstance(inp, dict)]
        if names:
            inputs_section = (
                f"\nPipeline 已宣告 inputs (用 $name 引用): "
                f"{', '.join('$' + n for n in names if n)}"
            )
    clarifications = state.get("clarifications") or {}
    clarify_section = ""
    if clarifications:
        clarify_section = (
            "\nUser 澄清: " + ", ".join(f"{k}={v}" for k, v in clarifications.items())
        )

    # On retry: surface the last attempt's validator errors so the LLM
    # knows which col-ref / dedup rule it violated. Without this the
    # retry has no signal that anything changed and the LLM emits the
    # same broken ops.
    prev_errors = state.get("plan_validation_errors") or []
    retry_section = ""
    if attempts > 1 and prev_errors:
        retry_section = (
            f"\n\n⚠ 你上次 compile 這 step 的 ops 被 validator 擋下，原因：\n"
            + "\n".join(f"  - {e[:300]}" for e in prev_errors[:4])
            + "\n這次請對照 UPSTREAM TRACE 的實際 cols 重寫，不要再用不在 cols 裡的欄位名。"
        )
        if any("leaf of nested" in e for e in prev_errors):
            retry_section += (
                "\n\n**這個 step 必須拆成 4 個 ops（不是 2 個）**：\n"
                "  1. add_node 一個解 nested 的 block (從 RELEVANT BLOCKS 找 unnest / explode 類型)，"
                "params={'column': '<父欄位>'}\n"
                "  2. connect 上游 → 新的解 nested node\n"
                "  3. add_node 原本想要的 filter/sort/chart block，column 用 leaf 名字\n"
                "  4. connect 解 nested node → 原本 block\n"
                "一次 emit 4 個 ops，logical id 接續編號。"
            )

    user_msg = (
        f"USER NEED:\n{(state.get('instruction') or '')[:600]}"
        f"{inputs_section}"
        f"{clarify_section}"
        f"{retry_section}"
        f"\n\nMACRO PLAN (context):\n" + "\n".join(context_lines) +
        f"\n\nCURRENT STEP:\n  step_idx={step.get('step_idx')}\n  text={step.get('text')}"
        f"\n  expected_kind={step.get('expected_kind')}"
        f"\n  expected_cols={step.get('expected_cols')}"
        f"\n  candidate_block={candidate or '(none)'}"
        f"\n\nUPSTREAM nodes already on canvas:\n{existing_nodes}"
        f"\n\nRELEVANT BLOCKS:\n{relevant_blocks}"
    )

    client = get_llm_client()
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )
    tracer = get_current_tracer()
    extra_sse: list[dict[str, Any]] = []

    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
        text = _strip_fence(resp.text or "")
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("compile_chunk_node: LLM/parse failed (%s) — retry %d/%d",
                       ex, attempts, MAX_COMPILE_ATTEMPTS)
        return {
            "compile_attempts": attempts_map,
            "plan_validation_errors": [f"compile step {step_key} failed: {ex}"],
            "sse_events": [_event("compile_chunk_error", {
                "step_idx": step.get("step_idx"),
                "error": str(ex)[:200],
                "attempts": attempts,
            })],
        }

    new_ops_raw = (decision or {}).get("ops") or []
    new_ops: list[dict[str, Any]] = []
    if isinstance(new_ops_raw, list):
        for op in new_ops_raw[:5]:
            if isinstance(op, dict) and op.get("type"):
                new_ops.append(op)

    # Deterministic dedup against existing plan — even if the LLM
    # violated Rule 1, drop colliding add_node + duplicate connect ops
    # so we don't end up with two real nodes sharing the same logical id
    # (which silently rebinds logical_to_real and breaks downstream refs).
    new_ops, dropped = _dedup_against_plan(new_ops, state.get("plan") or [])
    if dropped:
        logger.info(
            "compile_chunk_node: step %s dedup dropped %d op(s): %s",
            step_key, len(dropped), dropped[:4],
        )

    # Deterministic column-ref check — if the LLM emitted a filter /
    # sort / chart / select op referencing a column not in any upstream
    # node's exec_trace snapshot, retry compile_chunk with the issue in
    # plan_validation_errors instead of letting a doomed op enter the
    # plan and cascade through reflect_op. This is the main brake on
    # "filter column='chart_name'" / "sort by 'eventTime' after groupby"
    # style hallucinations.
    upstream_cols = _collect_upstream_cols(
        state.get("plan") or [], state.get("exec_trace") or {},
    )
    # Auto-fix #1: if any op references a leaf of a nested upstream col,
    # prepend an unnest of the parent + re-wire connects. Saves a
    # retry round-trip when the structural fix is unambiguous.
    new_ops, autofix_notes, autofix_leaves = _auto_insert_unnest(
        new_ops, state.get("plan") or [], upstream_cols, registry.catalog,
        exec_trace=state.get("exec_trace") or {},
    )
    if autofix_notes:
        logger.info(
            "compile_chunk_node: step %s unnest autofix: %s (added leaves: %s)",
            step_key, "; ".join(autofix_notes[:3]), sorted(autofix_leaves)[:8],
        )
        # Merge newly-exposed cols into upstream_cols so the validator
        # sees the unnest's flat output (otherwise the filter op that
        # triggered the auto-insert is still rejected as "leaf of nested").
        upstream_cols = upstream_cols | autofix_leaves

    # Auto-fix #2: when LLM chains chart→dataframe by mistake (multi-
    # analysis macro plans default to linear chaining), rewire each
    # connect's src to the latest dataframe-outputting node so each
    # chart branches from the shared upstream instead of consuming the
    # previous chart's chart_spec.
    new_ops, rewire_notes = _auto_rewire_chart_chains(
        new_ops, state.get("plan") or [], registry.catalog,
    )
    if rewire_notes:
        logger.info(
            "compile_chunk_node: step %s chart-chain autofix: %s",
            step_key, "; ".join(rewire_notes[:3]),
        )

    # Auto-fix #3: fuzzy-correct block_filter.value when LLM used a
    # shorthand from the user's prompt (e.g. 'xbar') that doesn't match
    # any actual observed leaf value (data has 'xbar_chart'). Mines the
    # exec_trace sample for the column's distinct observed values and
    # picks the unique substring match.
    autocorrect_notes = _autocorrect_filter_values(
        new_ops, state.get("plan") or [], state.get("exec_trace") or {},
    )
    if autocorrect_notes:
        logger.info(
            "compile_chunk_node: step %s filter-value autocorrect: %s",
            step_key, "; ".join(autocorrect_notes[:3]),
        )

    req_issues = _validate_required_params(new_ops, registry.catalog)
    col_issues = _validate_column_refs(new_ops, upstream_cols, registry.catalog)
    combined_issues = req_issues + col_issues
    if combined_issues:
        logger.warning(
            "compile_chunk_node: step %s attempt %d validation issues: req=%s col=%s — retry",
            step_key, attempts, req_issues[:3], col_issues[:3],
        )
        return {
            "compile_attempts": attempts_map,
            "plan_validation_errors": [
                f"step {step_key} validation failed: " + "; ".join(combined_issues[:4])
            ],
            "sse_events": [_event("compile_chunk_error", {
                "step_idx": step.get("step_idx"),
                "error": ("required_param_missing: " if req_issues else "column_ref_invalid: ")
                          + "; ".join(combined_issues[:2]),
                "attempts": attempts,
            })],
        }

    if not new_ops:
        logger.warning("compile_chunk_node: step %s produced 0 ops", step_key)
        return {
            "compile_attempts": attempts_map,
            "plan_validation_errors": [f"step {step_key} produced no valid ops"],
            "sse_events": [_event("compile_chunk_error", {
                "step_idx": step.get("step_idx"),
                "error": "no ops",
                "attempts": attempts,
            })],
        }

    # Append to plan; mark this macro step as completed (advanced after
    # ops actually execute via cursor reaching plan end).
    plan = list(state.get("plan") or [])
    plan.extend(new_ops)

    # Mark step as compiled (executor will mark completed via cursor)
    updated_macro = list(macro_plan)
    updated_macro[idx] = {
        **step,
        "ops_appended": (step.get("ops_appended", 0)) + len(new_ops),
        "compile_reason": (decision or {}).get("reason", "")[:200],
    }

    logger.info(
        "compile_chunk_node: step %s attempt %d → %d ops appended (plan now %d ops)",
        step_key, attempts, len(new_ops), len(plan),
    )

    if tracer is not None:
        llm_entry = tracer.record_llm(
            node="compile_chunk_node",
            system=_SYSTEM[:200] + "…",
            user_msg=user_msg[:2000],
            raw_response=resp.text or "",
            parsed=decision,
            step_idx=step.get("step_idx"),
            attempt=attempts,
        )
        sse = trace_event_to_sse(llm_entry, kind="llm_call")
        if sse: extra_sse.append(sse)
        step_entry = tracer.record_step(
            "compile_chunk_node", status="ok",
            step_idx=step.get("step_idx"),
            n_ops=len(new_ops), attempts=attempts,
        )
        sse2 = trace_event_to_sse(step_entry, kind="step")
        if sse2: extra_sse.append(sse2)

    return {
        "plan": plan,
        "macro_plan": updated_macro,
        "compile_attempts": attempts_map,
        "plan_validation_errors": [],
        "sse_events": [
            _event("chunk_compiled", {
                "step_idx": step.get("step_idx"),
                "step_text": step.get("text"),
                "n_ops": len(new_ops),
                "attempts": attempts,
                "reason": (decision or {}).get("reason", "")[:200],
            }),
            *extra_sse,
        ],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
