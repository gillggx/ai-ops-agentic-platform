"""block_apc_long_form — process_history wide → APC long format.

Sibling of block_spc_long_form. process_history flattens APC parameters as
`apc_<param>` (scalar value per parameter), with `apc_id` as a meta tag for
the APC run identifier. This block reshapes those columns into long form
so a single threshold + consecutive_rule pipeline can scan all parameters
in one sweep.

Output:  long DF with [<id_cols>, param_name, value]
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_ID_COLUMNS_DEFAULT = (
    "eventTime", "toolID", "lotID", "step", "spc_status", "fdc_classification",
    "apc_id",  # keep so downstream can correlate back to run
)
_APC_PREFIX = "apc_"
_APC_META_COLS = {"apc_id"}  # not reshaped — kept as id col


class ApcLongFormBlockExecutor(BlockExecutor):
    block_id = "block_apc_long_form"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT", message="'data' input must be a DataFrame"
            )

        if df.empty:
            return {"data": df.iloc[0:0].assign(
                param_name=pd.Series(dtype="object"),
                value=pd.Series(dtype="float64"),
            )}

        param_cols = [
            c for c in df.columns
            if c.startswith(_APC_PREFIX) and c not in _APC_META_COLS
        ]
        if not param_cols:
            raise BlockExecutionError(
                code="NO_APC_COLUMNS",
                message="No 'apc_<param>' columns found — does the upstream "
                        "process_history include APC data?",
            )

        present_id_cols = [c for c in _ID_COLUMNS_DEFAULT if c in df.columns]

        out = df.melt(
            id_vars=present_id_cols,
            value_vars=param_cols,
            var_name="param_name",
            value_name="value",
        )
        # Strip the `apc_` prefix so the param_name column is human-friendly
        out["param_name"] = out["param_name"].str.removeprefix(_APC_PREFIX)
        # Same UX consideration as spc_long_form — sort newest-first so
        # data_view / preview don't show a single param dominating.
        if "eventTime" in out.columns:
            out = out.sort_values(
                ["eventTime", "param_name"], ascending=[False, True],
            ).reset_index(drop=True)
        return {"data": out}
