"""block_apc_panel — composite APC chart block.

Sibling of block_spc_panel. APC params don't have UCL/LCL bounds in
process_history (unlike SPC), so this panel just plots multi-series
trends. event_filter modes the same: latest_drift / latest_event / all /
custom_time.

Note: latest_drift requires upstream to have an `is_drift` (or any
boolean violation) column — usually that lives downstream of block_delta
or block_threshold. Without violation_field set, latest_drift falls back
to latest_event semantics.
"""

from __future__ import annotations

from python_ai_sidecar.pipeline_builder.blocks._param_panel_base import _ParamPanelBase


class ApcPanelBlockExecutor(_ParamPanelBase):
    block_id = "block_apc_panel"

    nested_col = "apc_params"
    name_field = "param_name"
    value_field = "value"
    bound_fields = {}              # APC has no native bounds
    violation_field = "is_drift"   # consumed only when upstream provides it
    default_title = "APC Parameters"
    latest_violation_label = "latest_drift"
    process_history_object_name = "APC"
