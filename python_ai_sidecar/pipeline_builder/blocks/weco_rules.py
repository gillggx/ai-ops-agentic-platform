"""block_weco_rules — Western Electric control-chart rules for SPC.

Rules: R1/R2/R3/R4/R5/R6/R7/R8 (see _RULE_DESC).

Parameters decide σ derivation:
  sigma_source = "from_ucl_lcl"   (default) — uses ucl_column; σ = (UCL - center) / 3
                 "from_value"               — σ = std of value_column itself
                 "manual"                   — use manual_sigma number

Center line: center_column if given; else mean of value_column.

Output (PR-A evidence semantics):
  triggered (bool)      — any rule fired on any row
  evidence  (DataFrame) — **全部輸入 rows（按 group + sort_by 排序）**，加欄：
                           triggered_row     (bool)      — 該筆觸發任一 rule
                           triggered_rules   (str|None)  — 觸發的 rule ids（CSV e.g. "R1,R2"）
                           violation_side    (str|None)  — "above" / "below" / None
                           center, sigma     (float)     — 該 group 的 SPC 基線
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths
from python_ai_sidecar.pipeline_builder.path import ensure_flat_spc

_AVAILABLE_RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
_RULE_DESC = {
    "R1": "1 point > 3σ from center (OOC)",
    "R2": "9 consecutive points on same side of center (mean shift)",
    "R3": "6 consecutive points trending up or down (systematic trend)",
    "R4": "14 consecutive points alternating up/down (over-adjustment)",
    "R5": "2 of 3 consecutive points > 2σ same side (early warning)",
    "R6": "4 of 5 consecutive points > 1σ same side (gradual drift)",
    "R7": "15 consecutive points within ±1σ (stratification / sensor stuck)",
    "R8": "8 consecutive points outside ±1σ (bimodal distribution)",
}


def _consecutive_runs(mask: list[bool], required_length: int) -> list[int]:
    """Return end-indices of all consecutive-True runs >= required_length."""
    hits: list[int] = []
    start: Optional[int] = None
    length = 0
    for idx, v in enumerate(mask):
        if v:
            if start is None:
                start = idx
                length = 1
            else:
                length += 1
                if length >= required_length:
                    hits.append(idx)
        else:
            start = None
            length = 0
    return hits


def _k_of_n_runs(mask: list[bool], k: int, n: int) -> list[int]:
    """Return end-indices where within the last n points, at least k are True."""
    hits: list[int] = []
    if n > len(mask):
        return hits
    for end in range(n - 1, len(mask)):
        window = mask[end - n + 1 : end + 1]
        if sum(window) >= k:
            hits.append(end)
    return hits


def _monotonic_runs(values: list[float], required_length: int, direction: str) -> list[int]:
    """End-indices of runs of strict monotonic up/down points with length >= required.

    direction: 'up' means each point strictly greater than the previous.
    """
    hits: list[int] = []
    if len(values) < required_length:
        return hits
    run_start = 0
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        # NaN breaks the run
        if pd.isna(prev) or pd.isna(cur):
            run_start = i
            continue
        ok = (cur > prev) if direction == "up" else (cur < prev)
        if not ok:
            run_start = i
            continue
        length = i - run_start + 1
        if length >= required_length:
            hits.append(i)
    return hits


def _alternating_runs(values: list[float], required_length: int) -> list[int]:
    """End-indices of alternating up/down runs of length >= required.

    An alternating run means consecutive deltas flip sign at every step.
    """
    hits: list[int] = []
    if len(values) < required_length:
        return hits
    prev_sign = 0  # +1 for up, -1 for down, 0 = unknown
    run_start = 0
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        if pd.isna(prev) or pd.isna(cur) or cur == prev:
            prev_sign = 0
            run_start = i
            continue
        sign = 1 if cur > prev else -1
        if prev_sign != 0 and sign == -prev_sign:
            # continuing alternation
            length = i - run_start + 1
            if length >= required_length:
                hits.append(i)
        else:
            # reset to a new run starting at i-1
            run_start = i - 1
        prev_sign = sign
    return hits


def _all_within_runs(inside_mask: list[bool], required_length: int) -> list[int]:
    """End-indices where last `required_length` points are all within ±1σ."""
    return _consecutive_runs(inside_mask, required_length)


def _apply_rules_per_row(
    values: pd.Series,
    center: float,
    sigma: float,
    rules: list[str],
) -> tuple[list[list[str]], list[Optional[str]]]:
    """Evaluate selected rules — return (per_row_rule_ids, per_row_side).

    For each input row i, per_row_rule_ids[i] = list of rule ids fired AT that row
    (via any emit logic — either spot rule like R1, or run-terminating rule like R2).
    per_row_side[i] = 'above' / 'below' / None aggregated (preferred side at that row).
    """
    n = len(values)
    per_rule_ids: list[list[str]] = [[] for _ in range(n)]
    per_side: list[Optional[str]] = [None] * n

    numeric = pd.to_numeric(values, errors="coerce")

    above_3 = (numeric > center + 3 * sigma).tolist()
    below_3 = (numeric < center - 3 * sigma).tolist()
    above_2 = (numeric > center + 2 * sigma).tolist()
    below_2 = (numeric < center - 2 * sigma).tolist()
    above_1 = (numeric > center + sigma).tolist()
    below_1 = (numeric < center - sigma).tolist()
    above_0 = (numeric > center).tolist()
    below_0 = (numeric < center).tolist()

    def _hit(idx: int, rule: str, side: Optional[str]) -> None:
        if rule not in per_rule_ids[idx]:
            per_rule_ids[idx].append(rule)
        if side is not None and per_side[idx] is None:
            per_side[idx] = side

    if "R1" in rules:
        for i, v in enumerate(above_3):
            if v:
                _hit(i, "R1", "above")
        for i, v in enumerate(below_3):
            if v:
                _hit(i, "R1", "below")

    if "R2" in rules:
        for end in _consecutive_runs(above_0, 9):
            _hit(end, "R2", "above")
        for end in _consecutive_runs(below_0, 9):
            _hit(end, "R2", "below")

    if "R5" in rules:
        for end in _k_of_n_runs(above_2, 2, 3):
            _hit(end, "R5", "above")
        for end in _k_of_n_runs(below_2, 2, 3):
            _hit(end, "R5", "below")

    if "R6" in rules:
        for end in _k_of_n_runs(above_1, 4, 5):
            _hit(end, "R6", "above")
        for end in _k_of_n_runs(below_1, 4, 5):
            _hit(end, "R6", "below")

    if "R3" in rules:
        val_list = numeric.tolist()
        for end in _monotonic_runs(val_list, 6, "up"):
            _hit(end, "R3", "above")
        for end in _monotonic_runs(val_list, 6, "down"):
            _hit(end, "R3", "below")

    if "R4" in rules:
        for end in _alternating_runs(numeric.tolist(), 14):
            _hit(end, "R4", None)

    if "R7" in rules:
        inside_1s = ((numeric <= center + sigma) & (numeric >= center - sigma)).tolist()
        for end in _all_within_runs(inside_1s, 15):
            _hit(end, "R7", None)

    if "R8" in rules:
        outside_1s = ((numeric > center + sigma) | (numeric < center - sigma)).tolist()
        for end in _consecutive_runs(outside_1s, 8):
            _hit(end, "R8", None)

    return per_rule_ids, per_side


class WecoRulesBlockExecutor(BlockExecutor):
    block_id = "block_weco_rules"

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
        df = ensure_flat_spc(df)  # accept nested upstream

        value_column = self.require(params, "value_column")
        _center_col_pre = params.get("center_column") or None
        _ucl_col_pre = params.get("ucl_column") or None
        _group_by_pre = params.get("group_by") or None
        _sort_by_pre = params.get("sort_by") or None
        df = _materialize_paths(
            df,
            [c for c in (value_column, _center_col_pre, _ucl_col_pre, _group_by_pre, _sort_by_pre) if c],
        )
        if value_column not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"value_column '{value_column}' not in data"
            )

        rules = params.get("rules") or _AVAILABLE_RULES
        if isinstance(rules, str):
            rules = [r.strip() for r in rules.split(",") if r.strip()]
        invalid = [r for r in rules if r not in _AVAILABLE_RULES]
        if invalid:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"Unknown rule(s): {invalid}. Available: {_AVAILABLE_RULES}",
            )

        sigma_source = params.get("sigma_source", "from_ucl_lcl")
        if sigma_source not in {"from_ucl_lcl", "from_value", "manual"}:
            raise BlockExecutionError(
                code="INVALID_PARAM", message="sigma_source must be from_ucl_lcl / from_value / manual"
            )

        center_column: Optional[str] = params.get("center_column") or None
        ucl_column: Optional[str] = params.get("ucl_column") or None
        manual_sigma = params.get("manual_sigma")
        group_by: Optional[str] = params.get("group_by") or None
        sort_by: Optional[str] = params.get("sort_by") or None

        # Auto default sort_by = eventTime if present
        if sort_by is None and "eventTime" in df.columns:
            sort_by = "eventTime"

        chunks: list[pd.DataFrame] = []
        triggered_any = False

        groups: list[tuple[Any, pd.DataFrame]]
        if group_by and group_by in df.columns:
            groups = [(g, sub) for g, sub in df.groupby(group_by, dropna=False)]
        else:
            groups = [(None, df)]

        for group_label, sub_df in groups:
            work = (
                sub_df.sort_values(by=sort_by).reset_index(drop=True)
                if sort_by and sort_by in sub_df.columns
                else sub_df.reset_index(drop=True)
            )
            values = pd.to_numeric(work[value_column], errors="coerce")

            # Resolve center
            if center_column and center_column in work.columns:
                center_series = pd.to_numeric(work[center_column], errors="coerce")
                center = float(center_series.mean())
            else:
                center = float(values.mean())

            # Resolve sigma
            if sigma_source == "manual":
                if manual_sigma is None:
                    raise BlockExecutionError(
                        code="MISSING_PARAM",
                        message="sigma_source=manual requires manual_sigma number",
                    )
                sigma = float(manual_sigma)
            elif sigma_source == "from_value":
                sigma = float(values.std(ddof=0)) if len(values.dropna()) > 1 else 0.0
            else:  # from_ucl_lcl
                if not ucl_column or ucl_column not in work.columns:
                    raise BlockExecutionError(
                        code="MISSING_PARAM",
                        message="sigma_source=from_ucl_lcl requires ucl_column present in upstream data",
                    )
                ucl_series = pd.to_numeric(work[ucl_column], errors="coerce")
                ucl_mean = float(ucl_series.mean())
                sigma = (ucl_mean - center) / 3.0
                if sigma <= 0:
                    raise BlockExecutionError(
                        code="INVALID_INPUT",
                        message=(
                            f"Derived sigma <= 0 (UCL mean={ucl_mean}, center={center}). "
                            "Check that ucl_column is really the upper control limit."
                        ),
                    )

            per_rule_ids, per_side = _apply_rules_per_row(values, center, sigma, rules)
            triggered_flags = [len(ids) > 0 for ids in per_rule_ids]
            if any(triggered_flags):
                triggered_any = True

            work["triggered_row"] = triggered_flags
            work["triggered_rules"] = [",".join(ids) if ids else None for ids in per_rule_ids]
            work["violation_side"] = per_side
            work["center"] = center
            work["sigma"] = sigma
            if group_by:
                work["group"] = group_label
            chunks.append(work)

        evidence = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        return {
            "triggered": triggered_any,
            "evidence": evidence,
        }
