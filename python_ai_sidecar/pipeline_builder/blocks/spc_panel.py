"""block_spc_panel — composite SPC chart block.

What it does (in one block):
  1. (optional) explode `spc_charts` nested column from process_history(nested=true)
  2. pick the right event window via event_filter mode
       latest_ooc / latest_event / all / custom_time
  3. emit a multi-series chart_spec with UCL/LCL bound rules + OOC highlight

Why: 2026-05-14 smoke showed LLM composing primitive blocks (unnest →
filter → sort+limit=1 → line_chart) frequently collapses to a 1-point
chart. This block bakes in the right semantics so the LLM just picks me.
"""

from __future__ import annotations

from python_ai_sidecar.pipeline_builder.blocks._param_panel_base import _ParamPanelBase


class SpcPanelBlockExecutor(_ParamPanelBase):
    block_id = "block_spc_panel"

    nested_col = "spc_charts"
    name_field = "name"             # spc_charts[].name e.g. "xbar_chart"
    value_field = "value"
    bound_fields = {"ucl": "ucl", "lcl": "lcl"}
    violation_field = "is_ooc"
    default_title = "SPC Charts"
    latest_violation_label = "latest_ooc"
