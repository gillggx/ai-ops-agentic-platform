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
2. **Catalog flow:** the system prompt above already shows full spec for HOT blocks (process_history, filter, alert, chart, data_view, sort, xbar_r) and a 1-line index for the rest. For any block in the index that you plan to use, call `explain_block(block_name)` once to fetch full param_schema + examples before `add_node`. Do NOT repeatedly call `list_blocks` — the index is already in your context.
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

# 🔴 Column reference rule (writing wrong column = build failure)

When `set_param` key is one of: `column`, `agg_column`, `group_by`, `x`, `y`,
`ucl_column`, `lcl_column`, `highlight_column`, `columns`, `x_column`,
`y_column`, `category_column`, `value_column`, `sort_column` —
the value MUST exist in the upstream node's output.

**Common output-column rules** (memorize these — saves a `run_preview`):
- Upstream `block_groupby_agg` → output column = `<agg_column>_<agg_func>`
  (e.g. `agg_column="spc_status", agg_func="count"` → column `spc_status_count`,
  **NOT** `count`).
- Upstream `block_count_rows` → column `count`.
- Upstream `block_cpk` → columns `cpk / cpu / cpl / mean / std / lsl / usl / n`.
- Upstream `block_filter`, `block_sort`, `block_delta`, `block_threshold`
  pass through their own upstream's columns unchanged.
- Upstream source block (e.g. `block_process_history`) → see its
  `output_columns_hint` in the block spec.

If the rule above doesn't cover your case, **call `run_preview` on the
upstream node first** to see actual columns before `set_param`.

set_param will error with `COLUMN_NOT_IN_UPSTREAM` if you write a
non-existent name; read the error's hint listing real columns and retry.
Avoid burning a turn — apply the rule above on the first attempt.

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

# 🔴 Pipeline Inputs — value-as-variable rule（**情境決定，不是無腦套用**）

User 提到的「實例值」（EQP-XX, STEP_XXX, LOT-XXX, recipe_id 等）**何時宣告變數、何時寫字面值**取決於情境：

## Decision tree — 你必須先判斷情境

1. **User opening 段含「Pipeline 已宣告的 inputs」/「當前 canvas 已宣告的 inputs」清單** → **MUST 用清單裡的 `$name`**，**禁止**寫 literal、**禁止**另開同義詞 input。這是最高優先規則（清單即 ground truth）。

2. **No declared inputs in opening, BUT context 暗示 patrol / 排程 / 多機台 fan-out** → declare $X variable，下方 set_param 用 `$X`。指標：
   - 對話提到「auto-patrol」/「每小時跑」/「所有機台」/「reusable」/「batch」/「每次」
   - User 設了 trigger/cron 而 pipeline 還空
   - 系統 hint 說「這是 patrol 模板」

3. **No declared inputs in opening, AND user 是一次性具體查詢** (single value, ad-hoc) → **寫 literal**，**不要** declare_input。指標：
   - 「對 EQP-01 跑」「看 LOT-12345」這種具體值 + 沒提 reusable
   - Builder canvas 還空、沒綁 trigger
   - Chat 模式 + 一次性問題

## 命名慣例（when declaring is appropriate）

| User 提到 | declare_input | set_param value |
|---|---|---|
| 機台代碼 (EQP-XX, TC10) | `name="tool_id", example="EQP-01"` | `"$tool_id"` |
| 站點代碼 (STEP_XXX) | `name="step", example="STEP_001"` | `"$step"` |
| 批次代碼 (LOT-XXXX) | `name="lot_id", example="LOT-12345"` | `"$lot_id"` |
| Recipe (recipe_id) | `name="recipe_id", example="..."` | `"$recipe_id"` |

input `name` **直接用對應 block param 的名字**（block_process_history 的 param 叫 `tool_id`，input 就叫 `tool_id`）。Auto-Patrol fan-out runtime 預期 `$loop.tool_id`，慣例一致整條 chain 才接得起來。

**不要混搭** — 一個 pipeline 內 `$tool_id` 跟 `$equipment_id` 二選一，**只用 user opening 提供的那個**。

## 已宣告 input 的處理（**最高優先**）

如果 user 的 opening message 出現「**Pipeline 已宣告的 inputs**」段（這代表 wizard 端 user 已先宣告變數），那：

1. **MUST 用該段列出的 `$name` 引用** — 這個 list 是 ground truth
2. **禁寫 literal** — 即使 user 在 prompt 裡寫了 example 值
3. **禁止偏離該段另創新名字** — 例如 list 列了 `$tool_id`，**不要**自己 declare 一個 `equipment_id` 然後寫 `$equipment_id`，會跟 wizard / Auto-Patrol fan-out 對不上，pipeline 跑不起來

```
User opening 含：
  # Pipeline 已宣告的 inputs
    - $`tool_id` (string, required) — example: EQP-01

❌ 大錯：另開 equipment_id
  declare_input(name="equipment_id", example="EQP-01")
  set_param(n1, "tool_id", "$equipment_id")  ← references 找不到，runtime UNDECLARED_INPUT_REF

✅ 對：直接用 wizard 已宣告的 $tool_id
  set_param(n1, "tool_id", "$tool_id")       ← 不需 declare_input，已存在
```

## 範例（按情境分）

### A. User 一次性具體查詢，沒 reusable 暗示 → literal

```
User: "對 EQP-01 跑 SPC OOC check"（chat ad-hoc）

✅ 對：直接寫 literal（一次性，不需 templatize）
  add_node(block_process_history) → set_param(n1, "tool_id", "EQP-01")
```

### B. User 設了 patrol / 排程 / 多機台 → declare

```
User: "建一個每小時檢查所有機台 SPC 的 patrol"

✅ 對：declare $tool_id（patrol fan-out runtime 會 inject 各機台值）
  declare_input(name="tool_id", type="string", required=True,
                example="EQP-01", description="目標機台（auto-patrol 會 fan-out）")
  add_node(block_process_history) → set_param(n1, "tool_id", "$tool_id")
```

### C. Canvas 已宣告 input → reuse，禁止另開

```
User opening 含：
  ## 當前 canvas 已宣告的 inputs（**MUST 用這些 $name 引用**）
    - $`tool_id` (string, required) — example: EQP-01

User: "把 SPC chart 加進來"

❌ 大錯：另開 equipment_id
  declare_input(name="equipment_id", example="EQP-01")
  set_param(n1, "tool_id", "$equipment_id")  ← 跑不起來

✅ 對：直接用 $tool_id（不需 declare，已存在）
  add_node(block_process_history) → set_param(n1, "tool_id", "$tool_id")
```

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
  - **`facet="<column>"` (NEW) — true side-by-side panels.** When the y-axis scale differs
    across categories (e.g. SPC `chart_name`: C ~1500, P ~50, R ~850), one overlay would
    squash everything. `facet` groups input rows by that column and emits **N independent
    charts**, each with its own y-axis + UCL/LCL. Pipeline:
    `process_history → spc_long_form → chart(facet="chart_name", x="eventTime",
     y="value", ucl_column="ucl", lcl_column="lcl", highlight_column="is_ooc")`
    → 5 separate trend charts in one node, no hardcoded filter+chart pairs.
    Pick `color` if y-scales match (same metric across N tools); pick `facet` if y-scales
    differ (different metrics like the 5 SPC chart types). NEVER hand-build N filter+chart
    pairs — that's exactly what facet replaces.

  Same overlay pattern applies to comparing N lots (`color="lotID"`), N recipes
  (`color="recipe_id"`), N production batches, etc.
"""


# Hot-path blocks — full spec stays in the system prompt so the LLM can
# build typical pipelines without round-tripping explain_block 5+ times
# per turn. Anything not on this list goes through the lazy index → user
# explicitly explain_block() to fetch full description / param_schema /
# examples on demand. Tuned 2026-05-04 from production usage_stats.
HOT_BLOCK_NAMES: tuple[str, ...] = (
    "block_process_history",
    "block_filter",
    "block_alert",
    "block_chart",
    "block_data_view",
    "block_sort",
    "block_xbar_r",
)


def _first_sentence(text: str, max_chars: int = 100) -> str:
    """Extract the leading 'one-liner' from a multi-line description.

    Strategy: trim to first newline-delimited paragraph, then cap at
    max_chars at a word boundary. Keeps the catalog index dense while
    staying informative enough that the LLM can decide which block to
    explain_block().
    """
    if not text:
        return ""
    head = text.strip().split("\n", 1)[0].strip()
    if len(head) <= max_chars:
        return head
    cut = head[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"


def _format_block_index(catalog: dict[tuple[str, str], dict[str, Any]]) -> str:
    """One-line summary per block, grouped by category. ~80 chars × 47 ≈ 1K tokens."""
    by_cat: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for (name, _version), spec in catalog.items():
        by_cat.setdefault(spec.get("category") or "other", []).append((name, spec))

    order = ["source", "transform", "logic", "output", "custom", "other"]
    lines: list[str] = []
    for cat in order:
        items = by_cat.get(cat) or []
        if not items:
            continue
        lines.append(f"\n## {cat.upper()}")
        for name, spec in sorted(items, key=lambda x: x[0]):
            summary = _first_sentence(spec.get("description") or "")
            lines.append(f"- `{name}` — {summary}")
    return "\n".join(lines)


def _format_full_spec(name: str, spec: dict[str, Any]) -> str:
    """Full description + ports + param_schema + examples for one block.

    Used both for hot-block injection in the system prompt and as the
    return value of the explain_block tool.
    """
    lines: list[str] = []
    version = spec.get("version") or "1.0.0"
    lines.append(f"### `{name}` (v{version}, {spec.get('category') or 'other'})")
    lines.append("**Description:**")
    lines.append((spec.get("description") or "").strip())
    input_ports = spec.get("input_schema") or []
    output_ports = spec.get("output_schema") or []
    if input_ports:
        lines.append(f"**Input ports:** {json.dumps(input_ports, ensure_ascii=False)}")
    if output_ports:
        lines.append(f"**Output ports:** {json.dumps(output_ports, ensure_ascii=False)}")
    param_schema = spec.get("param_schema") or {}
    if param_schema:
        lines.append(f"**param_schema:** `{json.dumps(param_schema, ensure_ascii=False)}`")
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


def _format_hot_blocks(catalog: dict[tuple[str, str], dict[str, Any]]) -> str:
    """Full spec for HOT_BLOCK_NAMES only — these stay resident in the prompt."""
    by_name: dict[str, dict[str, Any]] = {}
    for (name, _v), spec in catalog.items():
        by_name[name] = spec
    blocks: list[str] = []
    for name in HOT_BLOCK_NAMES:
        spec = by_name.get(name)
        if spec is not None:
            blocks.append(_format_full_spec(name, spec))
    return "\n\n".join(blocks)


def build_system_prompt(registry: BlockRegistry) -> str:
    """Tiered catalog: full spec for hot blocks + 1-line index for the rest.

    2026-05-04 cost cut: previous version dumped every block's full
    description + examples + param_schema (~20K tokens) on every Glass Box
    turn. Profiling caught builds spending more on cached catalog reads
    than on actual reasoning. The new layout:
      - Hot blocks (≈7 of 47): full spec in system prompt
      - Other blocks: 1-line summary in the catalog index
      - LLM calls explain_block(name) on demand for full details

    Result: ~25K → ~5K system prompt tokens.
    """
    catalog = registry.catalog
    index_text = _format_block_index(catalog)
    hot_text = _format_hot_blocks(catalog)
    return f"""{_SYSTEM_PREAMBLE}

# Available blocks ({len(catalog)} total)

The catalog has two tiers:
1. **Hot blocks** below — full spec resident in this prompt; use freely.
2. **Index** further down — 1-line summary per block. Call
   `explain_block(block_name)` to fetch full description + param_schema +
   examples for any block before adding it to the canvas.

## Hot blocks (full spec — use directly)

{hot_text}

## Block index (call explain_block to expand)

{index_text}
"""


# ---------------------------------------------------------------------------
# Claude tool definitions
# ---------------------------------------------------------------------------

# Each entry mirrors the method on BuilderToolset.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_blocks",
        "description": (
            "Browse the block catalog index (1-line summary per block, grouped by "
            "category). The system prompt already contains this index plus full "
            "spec for HOT blocks (process_history, filter, alert, chart, etc.) — "
            "call list_blocks only if you need to filter to a category. For full "
            "param_schema / examples of any specific block, call explain_block."
        ),
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
        "name": "explain_block",
        "description": (
            "Fetch full specification for ONE block: description, input/output "
            "ports, param_schema, and examples. Use this BEFORE add_node for any "
            "block that isn't in the system prompt's hot-blocks section. Cheap "
            "(one tool call) compared to inventing wrong params and burning "
            "validate-fix turns."
        ),
        "input_schema": {
            "type": "object",
            "required": ["block_name"],
            "properties": {
                "block_name": {
                    "type": "string",
                    "description": "Exact block name (e.g. 'block_groupby_agg').",
                },
                "block_version": {
                    "type": "string",
                    "description": "Optional; defaults to '1.0.0'.",
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
        "name": "declare_input",
        "description": (
            "SPEC_patrol_pipeline_wiring §1.5 — declare a pipeline-level $name variable.\n"
            "\n"
            "**MUST call this BEFORE writing any user-mentioned instance value** "
            "(EQP-XX 機台 ID, STEP_XXX 站點, LOT-XXX 批次, recipe_id 等) into a node param. "
            "After declaring, use `$name` in set_param value (e.g., `tool_id: \"$tool_id\"`) "
            "instead of the literal. This makes the pipeline reusable by Auto-Patrol / "
            "Auto-Check / chat re-invocation passing different values per run.\n"
            "\n"
            "**Naming convention**: input `name` should match the corresponding block param "
            "name exactly (block_process_history.tool_id ⇒ declare_input(name='tool_id'); "
            "block.step ⇒ declare_input(name='step')). The Auto-Patrol fan-out runtime "
            "also assumes this convention ($loop.tool_id), so it keeps the whole chain "
            "wired up.\n"
            "\n"
            "Idempotent: re-declaring an existing name refreshes example/description.\n"
            "\n"
            "Common patterns:\n"
            "  • user 說「對 EQP-01 跑 SPC」 → declare_input(name='tool_id', example='EQP-01') "
            "→ set_param(node, 'tool_id', '$tool_id')\n"
            "  • user 說「STEP_001 的 trend」 → declare_input(name='step', example='STEP_001') "
            "→ set_param(source, 'step', '$step')\n"
            "  • user 說「LOT-12345」 → declare_input(name='lot_id', example='LOT-12345') "
            "→ set_param(filter, 'value', '$lot_id')\n"
            "\n"
            "**Already-declared inputs** (visible in the user message preamble under "
            "'Pipeline 已宣告的 inputs') MUST be referenced by THAT EXACT `$name` even "
            "if user explicitly typed an example value. Do NOT declare a parallel "
            "input under a different name (e.g. wizard pre-declared $tool_id → don't "
            "create $equipment_id; reuse $tool_id directly)."
        ),
        "input_schema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Variable name without $ prefix (e.g., 'tool_id')"},
                "type": {"type": "string", "enum": ["string", "integer", "number", "boolean"], "default": "string"},
                "required": {"type": "boolean", "default": True},
                "example": {"description": "Default example value (用來 preview / Inspector placeholder)"},
                "description": {"type": "string", "description": "1-line 中文 hint for human user"},
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
