"""block_unpivot — wide → long（pandas melt）。

Use case: SPC 寬表有 spc_xbar_chart_value / spc_r_chart_value / spc_s_chart_value / ...
         想要「對每個 chart_type 各跑一次 regression」 → melt 成 long 格式後配合
         下游 block 的 group_by 機制即可。

Input:   data (DataFrame)
Output:  data (DataFrame, long format)

Params:
  id_columns    (required, array) — 保留不動的識別欄位（eventTime, toolID, lotID, ...）
  value_columns (required, array) — 要 melt 成 long 的欄位（e.g. 5 個 SPC chart_value）
  variable_name (default='variable') — 新增的「原欄位名」欄位的名字
                 e.g. 'chart_type'（下游就可以 group_by=chart_type）
  value_name    (default='value')    — 新增的「原欄位值」欄位名
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths


class UnpivotBlockExecutor(BlockExecutor):
    block_id = "block_unpivot"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be DataFrame")

        id_columns = self.require(params, "id_columns")
        value_columns = self.require(params, "value_columns")
        if not isinstance(id_columns, list) or not all(isinstance(c, str) for c in id_columns):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="id_columns must be a list of strings"
            )
        if not isinstance(value_columns, list) or len(value_columns) < 1 or not all(isinstance(c, str) for c in value_columns):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="value_columns must be a non-empty list of strings"
            )

        df = _materialize_paths(df, list(id_columns) + list(value_columns))
        missing = [c for c in (id_columns + value_columns) if c not in df.columns]
        if missing:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"unpivot columns not in data: {missing}"
            )

        variable_name = params.get("variable_name") or "variable"
        value_name = params.get("value_name") or "value"

        out = df.melt(
            id_vars=id_columns,
            value_vars=value_columns,
            var_name=variable_name,
            value_name=value_name,
        )
        return {"data": out}
