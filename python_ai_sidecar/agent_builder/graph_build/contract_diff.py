"""contract_diff — compare an exec_trace snapshot to its declared contract.

v13 architecture (2026-05-13): plan_node asks the LLM to declare per-node
expectations (rows_min/max, cols_must_have, output_type, distinct_x_min,
etc.) at plan time. call_tool's auto-preview produces a snapshot per op;
this module diffs snapshot vs contract and returns a structured envelope
listing the specific violations.

Why this matters: previous reflect mechanism reacted to symptoms (rows=0,
preview error) without knowing what was *expected*. The LLM had to guess
whether 0 rows is a bug or genuinely sparse data. With contracts, the
LLM that wrote the plan declared "this node should have >=5 rows" — so
diff is unambiguous and the reflect prompt can be small and targeted.

Each diff result is an ErrorEnvelope-compatible dict (code / message /
node_id / given / expected / hint) — feeds straight into reflect_op.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def diff_snapshot_against_contract(
    *,
    logical_id: str,
    snapshot: dict[str, Any] | None,
    contract: dict[str, Any] | None,
    block_id: str | None = None,
) -> Optional[dict[str, Any]]:
    """Return an ErrorEnvelope-shaped dict if the snapshot violates the
    contract; None when it matches (or there's nothing to compare).

    snapshot shape (from exec_trace):
      {logical_id, real_id, block_id, rows, cols, sample, error, after_cursor}

    contract shape (from plan_node node_contracts):
      {rows_min?, rows_max?, cols_must_have?, output_type?, value_type?,
       distinct_x_min?, reason?}
    """
    if not contract:
        return None
    # Hard signal: preview itself errored — always a violation regardless
    # of what the contract said.
    err = (snapshot or {}).get("error")
    if err:
        return _envelope(
            code="DATA_SHAPE_WRONG",
            kind="op_executor_error",
            logical_id=logical_id,
            block_id=block_id,
            message=f"node '{logical_id}' preview raised: {str(err)[:200]}",
            given={"error": str(err)[:300]},
            expected={"status": "success"},
            reason=contract.get("reason"),
        )

    if not snapshot:
        # No snapshot — preview was skipped (e.g. non-source add_node without
        # connect yet). Don't fire a contract violation for that; we'll
        # check again after connect lands.
        return None

    rows = snapshot.get("rows")
    cols = snapshot.get("cols") or []
    sample = snapshot.get("sample")

    # Pull contract fields (treat missing as "no expectation").
    rows_min = _coerce_int(contract.get("rows_min"))
    rows_max = _coerce_int(contract.get("rows_max"))
    must_have = contract.get("cols_must_have") or []
    output_type = contract.get("output_type")
    distinct_x_min = _coerce_int(contract.get("distinct_x_min"))
    reason = contract.get("reason")

    # Row count checks (only when snapshot has integer rows).
    if isinstance(rows, int):
        if rows_min is not None and rows < rows_min:
            return _envelope(
                code="DATA_EMPTY" if rows == 0 else "DATA_SHAPE_WRONG",
                kind="contract_rows_min",
                logical_id=logical_id, block_id=block_id,
                message=(
                    f"node '{logical_id}' has {rows} rows but contract "
                    f"declared rows_min={rows_min}"
                ),
                given={"rows": rows},
                expected={"rows_min": rows_min},
                reason=reason,
            )
        if rows_max is not None and rows > rows_max:
            return _envelope(
                code="DATA_SHAPE_WRONG",
                kind="contract_rows_max",
                logical_id=logical_id, block_id=block_id,
                message=(
                    f"node '{logical_id}' has {rows} rows but contract "
                    f"declared rows_max={rows_max}"
                ),
                given={"rows": rows},
                expected={"rows_max": rows_max},
                reason=reason,
            )

    # Required columns. Path-aware: "a.b" matches if any col equals "a" (the
    # downstream consumer reads a.b via path syntax). For now we just check
    # top-level prefix match.
    if must_have and cols:
        cols_set = set(cols)
        missing: list[str] = []
        for must in must_have:
            if not isinstance(must, str):
                continue
            top = must.split(".")[0].split("[")[0]
            if must not in cols_set and top not in cols_set:
                missing.append(must)
        if missing:
            return _envelope(
                code="DATA_SHAPE_WRONG",
                kind="contract_cols_missing",
                logical_id=logical_id, block_id=block_id,
                message=(
                    f"node '{logical_id}' missing required column(s) "
                    f"{missing} (have: {list(cols)[:8]}{'…' if len(cols) > 8 else ''})"
                ),
                given={"cols": list(cols)[:20]},
                expected={"cols_must_have": must_have},
                reason=reason,
            )

    # Chart node — distinct x check (only when sample is iterable list/dict
    # with eventTime-like x_key).
    if distinct_x_min is not None and isinstance(sample, dict):
        # Snapshot for chart blocks puts {type, data, ...} in sample.
        data = sample.get("data") if "data" in sample else None
        x_key = sample.get("x_key") if "x_key" in sample else "eventTime"
        if isinstance(data, list) and data:
            distinct = {
                row.get(x_key) for row in data
                if isinstance(row, dict)
            }
            if len(distinct) < distinct_x_min:
                return _envelope(
                    code="DATA_SHAPE_WRONG",
                    kind="contract_distinct_x",
                    logical_id=logical_id, block_id=block_id,
                    message=(
                        f"chart '{logical_id}' has {len(distinct)} distinct "
                        f"{x_key} value(s); contract declared >={distinct_x_min}"
                    ),
                    given={"distinct_x": len(distinct), "x_key": x_key},
                    expected={"distinct_x_min": distinct_x_min},
                    reason=reason,
                )

    # output_type mismatch — coarse check; only fire when snapshot strongly
    # indicates a different shape. Skipped here because preview shape
    # detection is brittle; rely on cols_must_have + rows for now.
    _ = output_type  # noqa: F841

    return None


def _coerce_int(v: Any) -> int | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _envelope(
    *,
    code: str, kind: str, logical_id: str, block_id: str | None,
    message: str, given: dict[str, Any], expected: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    """Wrap a violation as the same envelope shape used elsewhere — see
    pipeline_builder/error_envelope.py for the canonical fields.
    """
    out: dict[str, Any] = {
        "code": code,
        "kind": kind,
        "node_id": logical_id,
        "block_id": block_id,
        "message": message,
        "given": given,
        "expected": expected,
    }
    if reason:
        out["rationale"] = reason[:200]
    return out
