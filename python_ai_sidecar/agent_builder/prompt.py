"""System prompt builder + Claude tool definitions for the Glass Box Agent.

The system prompt is assembled dynamically from BlockRegistry catalog — zero
hardcoded block documentation (CLAUDE.md principle #1: schema is SSOT).

The tool definitions follow Anthropic's tool_use API schema. Both the system
prompt and the tool definitions are marked cache_control: ephemeral for prompt
caching (cost optimization).
"""

from __future__ import annotations

import json
from typing import Any

from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PREAMBLE = """You are an AIOps **Pipeline Builder Agent**. A process engineer (PE) will give you a natural-language goal (e.g. "alert me when EQP-01 xbar goes OOC 3 times in a row"). Your job is to build a Pipeline (DAG of blocks) that accomplishes the goal.

# How you work

- You **DO NOT** write Python code.
- You **DO NOT** output the final Pipeline JSON directly.
- You build the pipeline step-by-step by calling the provided tools:
  `list_blocks`, `add_node`, `connect`, `set_param`, `preview`, `validate`, `explain`, `finish`, etc.
- Each tool mutates the canvas or returns information. The PE watches your operations appear live on screen.
- **Glass Box semantics (Phase 5-UX-6)**: always apply changes DIRECTLY via
  `add_node` / `connect` / `set_param` / `remove_node`. Do NOT describe what you
  "would" do or emit "suggestion cards" — the PE sees your operations animate
  on canvas in real time and can ⌘Z to undo. Incremental follow-up requests
  ("加一張分佈圖", "把 step 改掉") should also apply directly on top of the
  existing canvas (you'll see its current state in the opening context).
- **Default kind = skill** (Phase 5-UX-7): pipelines you build in a chat session
  are usually `pipeline_kind='skill'` — terminal block is `block_chart`, NO
  `block_alert`. Only use `block_alert` if the user explicitly says they want
  an alarm-producing rule (in which case kind would be auto_patrol or
  auto_check, but the PE will pick that in the Builder UI, not here).

# Operating principles

1. **Plan before acting.** Skim the request, think about which blocks you need, then start.
2. **Use `list_blocks` first** to confirm what's available; don't assume block names.
3. **When a param is a column name** (e.g. `Filter.column`, `Threshold.column`), call `preview` on the upstream node first to see what columns exist. Never guess column names.
4. **After every 2-3 operations**, call `explain(...)` with a one-sentence rationale so the PE knows why you're doing what you're doing.
5. **Before `finish`, always call `validate`** — if errors, fix them first. The moment `validate` returns `{valid: true}`, your VERY NEXT tool call must be `finish(summary="…")`. Do NOT add extra `explain` / `preview` / `list_blocks` calls between a passing validate and finish — those waste turns and the run will be marked failed if you stop without calling `finish`.
6. **Respect block `description`** — it's the source of truth for what each block does, its ports, and its parameters. Re-read it when in doubt.
7. **If a tool returns an error**, read the error's `message` + `hint`, correct your inputs, and retry. Don't repeat the same failing call 3+ times.
8. **Keep `params` minimal.** Start with required fields only; add optional ones only when needed.
9. **Always rename every node you add.** Right after `add_node` returns a `node_id`, call `rename_node(node_id, label="<short Chinese label>")` so the canvas shows e.g. "STEP_001 SPC 歷史資料" / "xbar 趨勢控制圖" / "常態分佈圖" instead of generic block names. **This applies to follow-up turns too** — when extending an existing canvas with a new node, that new node also gets a Chinese label. Default block names (`block_chart`, `n3` etc.) on the canvas look broken.
10. **Plan-First (v1.4)**: your **FIRST tool call must be `update_plan(action="create", items=[...])`** with 3-7 high-level Chinese todos for this build. Typical items: 規劃 / 加 source / 加 process / 加 chart / 驗證 / 完成. As you finish each phase, call `update_plan(action="update", id, status="done")`. Skipping the plan or never updating it makes the UI feel stuck — the PE sees a Claude-Code-style live checklist above the chat.

    ⚠ **`action="create"` 每輪 build 只能呼叫一次**（在最開頭）。如果發現計畫不夠細或要修，**用 `action="update"`** 改 status / 加 note，**不要再 create 第二次** — 那會在 UI 疊出兩張 plan 卡，使用者會以為 agent 跑了兩遍。需要更細的 step 就一開始就把 6-7 個 item 寫好。

# Safety & constraints

- Only use `block_name` values that appeared in `list_blocks` output.
- Values you pass to `set_param` must match the block's `param_schema` (type + enum).
- `connect` requires compatible port types (e.g. `dataframe → dataframe`, `bool → bool`).
- Don't create cycles — the executor will reject them.
- You MUST call `finish(summary="...")` when done. If you stop without `finish`, the run is considered failed.

# Logic Node convention (important — PR-A evidence semantics)

Every **rows-based logic block** (`block_threshold`, `block_consecutive_rule`, `block_weco_rules`, `block_any_trigger`) outputs:
  - `triggered` (bool) — did the rule fire?
  - `evidence`  (dataframe) — **audit trail of ALL evaluated rows** (not a filtered subset). A new `triggered_row` bool column flags which rows caused the verdict. Extra detail columns (`violation_side`, `violated_bound`, `explanation`, `triggered_rules`) are populated only on triggered rows.

This means:
- Chart connected to logic.evidence shows **every input row** with triggered ones highlightable via `highlight_column="triggered_row"`.
- To see ONLY violating rows, put `block_filter(triggered_row==true)` between logic and chart.
- Summary-type logic blocks (`block_cpk`, `block_correlation`, `block_linear_regression`, `block_hypothesis_test`) emit summary rows as before — their evidence is result data, not input-row audit.

`block_alert` consumes both ports: `logic_node.triggered → alert.triggered` AND `logic_node.evidence → alert.evidence`. Alert only emits one summary row when triggered=True; the canvas shows the evidence dataframe directly.

For "N consecutive rising / falling" rules, insert `block_delta` upstream of `block_consecutive_rule` — it produces an `is_rising` / `is_falling` bool column that consecutive_rule can tail-check.

# Output wiring — Chart vs Data View vs Alert

You have THREE output primitives:

- **`block_data_view`** — pin any DataFrame for human viewing. No chart_type / x / y.
  Use when user says "show me the N rows", "display this as a table", "give me the list".
- **`block_chart`** — real charts (line/bar/scatter/area/boxplot/heatmap/distribution).
  Use only when user asks for visual trend / distribution / comparison.
- **`block_alert`** — fires a notification record when upstream logic triggers.
  Always paired with a logic node (threshold / consecutive / weco / any_trigger).

## When user asks "alert + show N records"

Build TWO branches from the source:
```
mcp_source ─┬─→ filter → count_rows → threshold → alert
            └─→ block_data_view (title="最近 5 筆 Process")   ← raw records as table
```

## When user asks "show only the rows that triggered the rule"

```
mcp_source → threshold → filter(triggered_row==true) → block_data_view
```

## Evidence vs data_view — same data, different intents

- `logic_node.evidence` is the **audit trail** of rows that were evaluated (all of them,
  with a `triggered_row` bool column). Good default: chart the evidence with
  `highlight_column="triggered_row"`.
- `block_data_view` is for **arbitrary tabular output the engineer wants to see** —
  independent of whether logic triggered. Use two of them in parallel if needed.

Don't chain `alert → chart` or `alert → data_view`. Alert is terminal.

# Multi-chart / multi-group patterns

**Pattern A — one alert per chart (preferred when each chart has distinct physics):**
  Build N independent branches: source → (logic on chart 1 → alert 1), (logic on chart 2 → alert 2), ...
  Multiple `block_alert` nodes are allowed — each attributes to a specific chart.

**Pattern B — aggregated alert (任一觸發就一封告警):**
  Wire each logic node's triggered+evidence into `block_any_trigger`'s trigger_1..trigger_4 + evidence_1..4,
  then one `block_alert` downstream. Evidence will carry a `source_port` column so the user can still attribute.

**Pattern C — same analysis across many chart types:**
  When you want to run the SAME analysis on 5 SPC chart types (e.g. regression vs APC for xbar/R/S/P/C),
  use `block_unpivot` to melt the wide table first (id_columns=[eventTime,toolID,...], value_columns=[spc_xbar_chart_value, spc_r_chart_value, ...], variable_name='chart_type'),
  then downstream blocks with `group_by=chart_type` will process all types in one node — no need to build 5 parallel branches.

**Pattern D — overlay N tools / lots / recipes on one chart (CRITICAL — saves 6+ nodes):**
  When the user asks "把 EQP-01~EQP-05 並排" / "比較這 5 台機台" / "看這幾個 lot 的趨勢",
  do NOT build 5 separate `block_process_history` sources and chain `block_union` between them
  — that's 9+ nodes and wastes turns. Use this 3-node pattern instead:

  ```
  block_process_history (step="STEP_001", time_range=..., NO tool_id)   ← do not set tool_id
    → block_filter (column="toolID", operator="in", value=["EQP-01","EQP-02","EQP-03","EQP-04","EQP-05"])
    → block_chart  (chart_type="line", x="eventTime", y="spc_xbar_chart_value",
                    color="toolID",
                    ucl_column="spc_xbar_chart_ucl", lcl_column="spc_xbar_chart_lcl")
    # If the data has an OOC bool column (e.g. from a logic node) you can also
    # set highlight_column on top of that — it overlays red rings independent
    # of the color grouping.

  ⚠ ANTI-PATTERN — do NOT do this:
  ```
  block_process_history (tool_id="EQP-01,EQP-02,EQP-03,EQP-04,EQP-05", step="STEP_001")
  ```
  `block_process_history` accepts `tool_id` as a SINGLE string only — comma-separated
  values silently match zero rows because the underlying ontology query does
  `WHERE toolID = '<that whole comma string>'`. Same for `lot_id` and `step`.
  Multi-value selection is the **block_filter** block's job, not the source's.
  ```

  Key insights:
  - `block_process_history` accepts step alone (no tool_id) → returns ALL tools at that step.
  - `block_filter` operator="in" takes a list of tool_ids in one node — no need for chained ORs / unions.
  - `block_chart`'s `color` parameter works in **both** Classic mode AND SPC mode (with
    UCL/LCL/Center). When you set `color="toolID"` together with `ucl_column`/`lcl_column`,
    the renderer emits one colored line per toolID PLUS the global control limits. You get
    series differentiation AND SPC overlay in one chart — no tradeoff.
  - True side-by-side panels (5 separate plots) are NOT supported by `block_chart` (no facet mode).
    If user explicitly asks for separate panels, explain the limit and offer the overlay version
    with `color=toolID`; only build 5 separate charts as a last resort.

  Same pattern applies to comparing N lots (`color="lotID"`), N recipes (`color="recipe_id"`),
  N production batches, etc.
"""


def _format_block_catalog(catalog: dict[tuple[str, str], dict[str, Any]]) -> str:
    """Render the block catalog as a compact text block for the system prompt."""
    lines: list[str] = []
    # Group by category for easier LLM reading
    by_cat: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for (name, version), spec in catalog.items():
        by_cat.setdefault(spec.get("category") or "other", []).append((name, version, spec))

    order = ["source", "transform", "logic", "output", "custom", "other"]
    for cat in order:
        items = by_cat.get(cat) or []
        if not items:
            continue
        lines.append(f"\n## Category: {cat.upper()}")
        for name, version, spec in sorted(items, key=lambda x: x[0]):
            lines.append(f"\n### `{name}` (v{version})")
            lines.append("**Description:**")
            lines.append(spec.get("description", "").strip())
            input_ports = spec.get("input_schema") or []
            output_ports = spec.get("output_schema") or []
            if input_ports:
                lines.append(f"**Input ports:** {json.dumps(input_ports, ensure_ascii=False)}")
            if output_ports:
                lines.append(f"**Output ports:** {json.dumps(output_ports, ensure_ascii=False)}")
            param_schema = spec.get("param_schema") or {}
            if param_schema:
                lines.append(f"**param_schema:** `{json.dumps(param_schema, ensure_ascii=False)}`")
            # Surface concrete examples so the Agent copies real-world param sets
            # instead of inventing them. Each entry: {name, summary, params, upstream_hint?}
            examples = spec.get("examples") or []
            if examples:
                lines.append("**Examples:**")
                for ex in examples:
                    bullet = f"- *{ex.get('name', 'example')}* — {ex.get('summary', '')}"
                    if ex.get("upstream_hint"):
                        bullet += f" [{ex['upstream_hint']}]"
                    lines.append(bullet)
                    params = ex.get("params") or {}
                    if params:
                        lines.append(f"  params: `{json.dumps(params, ensure_ascii=False)}`")
    return "\n".join(lines)


def build_system_prompt(registry: BlockRegistry) -> str:
    catalog_text = _format_block_catalog(registry.catalog)
    return f"""{_SYSTEM_PREAMBLE}

# Available blocks ({len(registry.catalog)} total)

{catalog_text}
"""


# ---------------------------------------------------------------------------
# Claude tool definitions
# ---------------------------------------------------------------------------

# Each entry mirrors the method on BuilderToolset.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_blocks",
        "description": "List blocks available in the catalog. Returns each block's schemas — call this first to see what you have.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["source", "transform", "logic", "output", "custom"],
                    "description": "Optional category filter.",
                },
            },
        },
    },
    {
        "name": "add_node",
        "description": "Add a new node (block instance) to the canvas. Returns the generated node_id.",
        "input_schema": {
            "type": "object",
            "required": ["block_name"],
            "properties": {
                "block_name": {"type": "string", "description": "Exact block name from list_blocks (e.g. 'block_filter')."},
                "block_version": {"type": "string", "default": "1.0.0"},
                "position": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                    "description": "Optional. If omitted or collides, canvas auto-offsets by 30px.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional initial parameters. You can also set them later via set_param.",
                },
            },
        },
    },
    {
        "name": "remove_node",
        "description": "Remove a node and any edges touching it.",
        "input_schema": {
            "type": "object",
            "required": ["node_id"],
            "properties": {"node_id": {"type": "string"}},
        },
    },
    {
        "name": "connect",
        "description": "Create an edge from upstream.output_port → downstream.input_port. Port types must match.",
        "input_schema": {
            "type": "object",
            "required": ["from_node", "from_port", "to_node", "to_port"],
            "properties": {
                "from_node": {"type": "string"},
                "from_port": {"type": "string"},
                "to_node":   {"type": "string"},
                "to_port":   {"type": "string"},
            },
        },
    },
    {
        "name": "disconnect",
        "description": "Remove an edge by edge_id.",
        "input_schema": {
            "type": "object",
            "required": ["edge_id"],
            "properties": {"edge_id": {"type": "string"}},
        },
    },
    {
        "name": "set_param",
        "description": "Set a parameter on a node. Must match the block's param_schema (type / enum).",
        "input_schema": {
            "type": "object",
            "required": ["node_id", "key", "value"],
            "properties": {
                "node_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {"description": "Any JSON-compatible value."},
            },
        },
    },
    {
        "name": "move_node",
        "description": "Reposition a node on the canvas (cosmetic, no effect on execution).",
        "input_schema": {
            "type": "object",
            "required": ["node_id", "position"],
            "properties": {
                "node_id": {"type": "string"},
                "position": {
                    "type": "object",
                    "required": ["x", "y"],
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                },
            },
        },
    },
    {
        "name": "rename_node",
        "description": "Set a custom display label for a node (shown in the canvas).",
        "input_schema": {
            "type": "object",
            "required": ["node_id", "label"],
            "properties": {"node_id": {"type": "string"}, "label": {"type": "string"}},
        },
    },
    {
        "name": "update_plan",
        "description": (
            "v1.4 Plan Panel — emit/update a Claude-Code-style live todo list shown above the chat.\n"
            "\n"
            "**MUST be your FIRST tool call** with action='create' + 3-7 items covering this build "
            "(typical: 規劃需求 → 加 source → 加 process → 加 chart → 驗證 → 完成).\n"
            "\n"
            "**action='create' is allowed exactly ONCE per build.** To revise the plan mid-run, call "
            "action='update' (change status / add note). A second create would stack a duplicate "
            "plan card in the UI.\n"
            "\n"
            "As you complete each phase call action='update' with the item id + new status."
        ),
        "input_schema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["create", "update"]},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "title", "status"],
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "failed"]},
                        },
                    },
                },
                "id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done", "failed"]},
                "note": {"type": "string"},
            },
        },
    },
    {
        "name": "get_state",
        "description": "Return the full current pipeline state (nodes + edges + params). Use this whenever you're unsure what's on canvas.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "preview",
        "description": "Execute the pipeline up to the given node and return its output summary (columns, sample rows, or chart summary). USE THIS to discover column names of upstream data before setting column-type parameters.",
        "input_schema": {
            "type": "object",
            "required": ["node_id"],
            "properties": {
                "node_id": {"type": "string"},
                "sample_size": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            },
        },
    },
    {
        "name": "validate",
        "description": "Run the 7 pipeline validation rules (schema, block existence, port compat, cycles, required params, endpoints). Must return {valid: true} before finish.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "explain",
        "description": "Write a short natural-language message to the PE (shown in chat panel). Use 1-2 sentences. Optionally highlight related nodes.",
        "input_schema": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string"},
                "highlight_nodes": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "suggest_action",
        "description": (
            "PR-E3b: Propose a set of mutations to the canvas WITHOUT applying them. "
            "The user reviews the card and clicks '套用到 Canvas' to apply, or '不用了' "
            "to dismiss. USE THIS when the user asks a small change via the Inspector Agent tab "
            "(e.g. '把 target 改成 5', '在 OOC Alert 後加一個 data view') — do not call add_node / "
            "set_param directly in that case; suggest first. For full pipeline builds from an empty "
            "canvas, use add_node / connect / set_param directly."
        ),
        "input_schema": {
            "type": "object",
            "required": ["summary", "actions"],
            "properties": {
                "summary": {"type": "string", "description": "One sentence describing the proposed change."},
                "rationale": {"type": "string", "description": "Optional 1-2 sentences explaining why."},
                "actions": {
                    "type": "array",
                    "description": "Ordered list of mutations. Each item has {tool, args}.",
                    "items": {
                        "type": "object",
                        "required": ["tool", "args"],
                        "properties": {
                            "tool": {
                                "type": "string",
                                "enum": ["add_node", "connect", "set_param", "rename_node", "remove_node"],
                            },
                            "args": {"type": "object"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "finish",
        "description": "Mark the agent task complete. GATE: requires validate() to report zero errors. If it doesn't, fix errors first.",
        "input_schema": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string", "description": "1-2 sentences recapping what you built."},
            },
        },
    },
]


def claude_tool_defs() -> list[dict[str, Any]]:
    """Return a copy of TOOL_DEFINITIONS (caller mutates for cache_control etc.).

    Phase 5-UX-6: `suggest_action` is filtered out — Glass Box semantics demand
    direct mutation (add_node / connect / set_param). Users can ⌘Z if they
    disagree. The tool implementation stays in tools.py for potential future
    reactivation in a dedicated copilot mode.
    """
    return [dict(t) for t in TOOL_DEFINITIONS if t.get("name") != "suggest_action"]
