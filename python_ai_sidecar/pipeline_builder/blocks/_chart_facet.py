"""Shared facet (small-multiples) helper for chart blocks.

Lifted out of block_chart so the new dedicated chart blocks
(block_line_chart, block_bar_chart, block_scatter_chart, …) can support
the same `facet=<column>` param without each duplicating the recursion
+ collection logic.

Why a free function and not a mixin: chart blocks may have completely
different params (xbar_r needs subgroup_column, wafer_heatmap needs x/y
coords) — passing the executor as a callback keeps the helper agnostic
to per-block validation.

Output convention: chart_spec is a list when faceted, a single dict when
not — matches the existing `_collect_chart_summaries` expansion path so
no frontend changes are needed.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    ExecutionContext,
)


# Type alias for the inner non-faceted execute (recursion target).
ChartExecute = Callable[
    [dict[str, Any], dict[str, Any], ExecutionContext],
    Awaitable[dict[str, Any]],
]


async def maybe_facet(
    *,
    params: dict[str, Any],
    inputs: dict[str, Any],
    context: ExecutionContext,
    inner: ChartExecute,
) -> dict[str, Any] | None:
    """If `params['facet']` is set, group input df by that column and run
    `inner` once per group. Returns ``{'chart_spec': [s1, s2, …]}``.

    If facet is unset (or None), returns ``None`` so the caller proceeds
    with its normal single-chart path. Pattern:

        async def execute(self, *, params, inputs, context):
            # ... validate top-level inputs ...
            faceted = await maybe_facet(
                params=params, inputs=inputs, context=context,
                inner=lambda p, i, c: self._render_one(p, i, c),
            )
            if faceted is not None:
                return faceted
            # ... single-chart path ...

    Caller's `inner` MUST NOT recurse into facet — pass a function that
    does the single-chart rendering directly. The helper strips `facet`
    from the params it forwards.
    """
    facet_col = params.get("facet")
    if not facet_col:
        return None

    df = inputs.get("data")
    if not isinstance(df, pd.DataFrame):
        raise BlockExecutionError(
            code="INVALID_INPUT",
            message="facet requires 'data' input to be a DataFrame",
        )
    if facet_col not in df.columns:
        raise BlockExecutionError(
            code="COLUMN_NOT_FOUND",
            message=f"facet column '{facet_col}' not in data",
        )

    # Strip facet so inner doesn't see it.
    sub_params = {k: v for k, v in params.items() if k != "facet"}
    base_title = params.get("title")

    specs: list[dict[str, Any]] = []
    # `sort=False` preserves insertion order (matches block_chart's behaviour
    # so X̄/R/S/P/C panels stay in the user's original column order).
    for group_key, group_df in df.groupby(facet_col, sort=False):
        gp = dict(sub_params)
        # Per-panel title — append the group key so each card is identifiable.
        if base_title:
            gp["title"] = f"{base_title} — {group_key}"
        else:
            gp["title"] = str(group_key)
        sub_inputs = {**inputs, "data": group_df.reset_index(drop=True)}
        sub_result = await inner(gp, sub_inputs, context)
        spec = sub_result.get("chart_spec")
        if isinstance(spec, list):
            # Defensive: nested facet (shouldn't happen but flatten anyway)
            specs.extend(spec)
        elif spec is not None:
            specs.append(spec)
    return {"chart_spec": specs}
