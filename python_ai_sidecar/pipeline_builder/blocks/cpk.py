"""block_cpk — Process capability Cp/Cpk/Pp/Ppk。

Semiconductor-standard capability metrics for a monitored numeric column
against spec limits (USL / LSL).

Definitions:
  σ_short  = sample standard deviation within the dataset (ddof=1)  — 短期變異
  σ_long   = same dataset std (no within-group decomposition)       — 長期變異
             (Phase β MVP treats short = long; future β' can take subgroup_column)
  Cp  = (USL - LSL) / (6 σ_short)
  Cpu = (USL - μ)   / (3 σ_short)
  Cpl = (μ - LSL)   / (3 σ_short)
  Cpk = min(Cpu, Cpl)
  Pp/Ppk use σ_long; in this MVP they equal Cp/Cpk.

Supports single-sided (only USL or only LSL). Errors if both missing.

Input:  data (DataFrame)
Output: stats (DataFrame) — per group row: mu / sigma / n / cp / cpu / cpl / cpk / pp / ppk
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths


def _compute_capability(
    values: np.ndarray,
    usl: Optional[float],
    lsl: Optional[float],
) -> dict[str, Any]:
    n = int(len(values))
    if n < 2:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA", message=f"Cpk needs n>=2 samples (got n={n})"
        )
    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1))
    if sigma <= 0:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA",
            message=f"sample std is 0 — Cpk undefined for constant data",
        )

    cpu = (usl - mu) / (3 * sigma) if usl is not None else None
    cpl = (mu - lsl) / (3 * sigma) if lsl is not None else None
    if usl is not None and lsl is not None:
        cp = (usl - lsl) / (6 * sigma)
        cpk = min(cpu, cpl)  # type: ignore[type-var]
    elif usl is not None:
        cp = None
        cpk = cpu
    else:
        cp = None
        cpk = cpl

    return {
        "n": n,
        "mu": mu,
        "sigma": sigma,
        "cp": cp,
        "cpu": cpu,
        "cpl": cpl,
        "cpk": cpk,
        "pp": cp,       # MVP: pp = cp (long=short)
        "ppk": cpk,     # MVP: ppk = cpk
    }


class CpkBlockExecutor(BlockExecutor):
    block_id = "block_cpk"

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

        value_col: str = self.require(params, "value_column")
        _group_by_pre = params.get("group_by") or None
        df = _materialize_paths(df, [c for c in (value_col, _group_by_pre) if c])
        if value_col not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data"
            )

        usl = params.get("usl")
        lsl = params.get("lsl")
        if usl is None and lsl is None:
            raise BlockExecutionError(
                code="MISSING_PARAM", message="At least one of usl / lsl is required"
            )
        usl_f = float(usl) if usl is not None else None
        lsl_f = float(lsl) if lsl is not None else None
        if usl_f is not None and lsl_f is not None and usl_f <= lsl_f:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"usl ({usl_f}) must be > lsl ({lsl_f})"
            )

        group_by: Optional[str] = params.get("group_by") or None
        if group_by is not None and group_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"group_by '{group_by}' not in data"
            )

        if group_by:
            iterable = [(g, sub) for g, sub in df.groupby(group_by, dropna=False)]
        else:
            iterable = [(None, df)]

        rows: list[dict[str, Any]] = []
        for group_label, sub in iterable:
            vals = pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy(dtype=float)
            stats = _compute_capability(vals, usl_f, lsl_f)
            stats["group"] = group_label
            stats["usl"] = usl_f
            stats["lsl"] = lsl_f
            rows.append(stats)
        return {"stats": pd.DataFrame(rows)}
