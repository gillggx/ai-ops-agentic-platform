"""block_hypothesis_test — common hypothesis tests (t-test / ANOVA / chi-square).

Supports 3 test_type:
  - "t_test"     : compare 2 groups' means (Welch's t-test)
  - "anova"      : compare 3+ groups' means (one-way ANOVA)
  - "chi_square" : independence test between two categorical columns

Input:  data (DataFrame)
Output: stats (DataFrame) — test / statistic / p_value / alpha / significant(bool)
                            + test-specific fields (df, groups, etc.)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as _stats

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths


_TESTS = {"t_test", "anova", "chi_square"}


def _run_t_test(df: pd.DataFrame, value_col: str, group_col: str, alpha: float) -> dict[str, Any]:
    groups = [
        pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        for _, sub in df.groupby(group_col, dropna=False)
    ]
    labels = [str(g) for g, _ in df.groupby(group_col, dropna=False)]
    if len(groups) != 2:
        raise BlockExecutionError(
            code="INVALID_INPUT",
            message=f"t_test requires exactly 2 groups, got {len(groups)} from '{group_col}'",
        )
    a, b = groups
    if len(a) < 2 or len(b) < 2:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA",
            message=f"t_test needs n>=2 per group (got {len(a)} / {len(b)})",
        )
    res = _stats.ttest_ind(a, b, equal_var=False)  # Welch's t
    return {
        "test": "t_test",
        "groups": " vs ".join(labels),
        "statistic": float(res.statistic),
        "p_value": float(res.pvalue),
        "df": float(getattr(res, "df", len(a) + len(b) - 2)),
        "n_a": len(a),
        "n_b": len(b),
        "mean_a": float(np.mean(a)),
        "mean_b": float(np.mean(b)),
        "alpha": alpha,
        "significant": bool(res.pvalue < alpha),
    }


def _run_anova(df: pd.DataFrame, value_col: str, group_col: str, alpha: float) -> dict[str, Any]:
    groups = [
        pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        for _, sub in df.groupby(group_col, dropna=False)
    ]
    labels = [str(g) for g, _ in df.groupby(group_col, dropna=False)]
    if len(groups) < 3:
        raise BlockExecutionError(
            code="INVALID_INPUT",
            message=f"anova requires >=3 groups, got {len(groups)} (use t_test for 2 groups)",
        )
    if any(len(g) < 2 for g in groups):
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA",
            message="anova needs n>=2 per group",
        )
    res = _stats.f_oneway(*groups)
    return {
        "test": "anova",
        "groups": ", ".join(labels),
        "statistic": float(res.statistic),
        "p_value": float(res.pvalue),
        "k": len(groups),
        "n_total": sum(len(g) for g in groups),
        "alpha": alpha,
        "significant": bool(res.pvalue < alpha),
    }


def _run_chi_square(df: pd.DataFrame, group_col: str, target_col: str, alpha: float) -> dict[str, Any]:
    # contingency table: group_col × target_col
    contingency = pd.crosstab(df[group_col], df[target_col])
    if contingency.shape[0] < 2 or contingency.shape[1] < 2:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA",
            message=f"chi_square needs at least 2×2 contingency (got {contingency.shape})",
        )
    chi2, p, dof, _expected = _stats.chi2_contingency(contingency.to_numpy())
    return {
        "test": "chi_square",
        "groups": f"{group_col} × {target_col}",
        "statistic": float(chi2),
        "p_value": float(p),
        "df": int(dof),
        "n_total": int(contingency.to_numpy().sum()),
        "alpha": alpha,
        "significant": bool(p < alpha),
    }


class HypothesisTestBlockExecutor(BlockExecutor):
    block_id = "block_hypothesis_test"

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

        test_type = self.require(params, "test_type")
        if test_type not in _TESTS:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"test_type must be one of {_TESTS}"
            )

        alpha = float(params.get("alpha", 0.05))
        if not (0.0 < alpha < 1.0):
            raise BlockExecutionError(code="INVALID_PARAM", message="alpha must be in (0, 1)")

        group_col = self.require(params, "group_column")
        _path_cols: list[str] = [group_col]
        if test_type == "chi_square":
            _tc = params.get("target_column")
            if isinstance(_tc, str) and _tc:
                _path_cols.append(_tc)
        else:
            _vc = params.get("value_column")
            if isinstance(_vc, str) and _vc:
                _path_cols.append(_vc)
        df = _materialize_paths(df, _path_cols)
        if group_col not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"group_column '{group_col}' not in data"
            )

        if test_type == "chi_square":
            target_col = self.require(params, "target_column")
            if target_col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"target_column '{target_col}' not in data"
                )
            result = _run_chi_square(df, group_col, target_col, alpha)
        else:
            value_col = self.require(params, "value_column")
            if value_col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data"
                )
            result = (
                _run_t_test(df, value_col, group_col, alpha)
                if test_type == "t_test"
                else _run_anova(df, value_col, group_col, alpha)
            )

        return {"stats": pd.DataFrame([result])}
