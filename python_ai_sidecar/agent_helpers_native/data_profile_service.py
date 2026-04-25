"""DataProfileService — v15.0 Smart Sampling Interceptor.

Generates a DataProfile for any tool result containing a sizeable dataset
(list-of-dicts with > 5 rows).  The profile is attached to the tool result
as ``result["_data_profile"]`` and later injected as hidden context into
the next LLM prompt by AgentOrchestrator.

DataProfile schema
------------------
{
    "sample":  [first 20 rows as list-of-dicts],
    "meta":    {col: {"dtype": str, "null_count": int, "unique_count": int}},
    "stats":   {col: {"min": float|str, "max": float|str, "mean": float}}  # numeric only
}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try pandas for accurate dtype / stats
try:
    import pandas as _pd  # type: ignore
except ImportError:
    _pd = None

_MIN_ROWS = 5   # minimum rows to trigger profiling
_SAMPLE_N = 20  # rows to include in sample
_META_N   = 50  # rows to scan for meta stats


# ── Public API ──────────────────────────────────────────────────────────────

def is_data_source(result: Any) -> bool:
    """Return True if *result* contains a list-of-dicts with > _MIN_ROWS rows."""
    dataset = _extract_dataset(result)
    return dataset is not None and len(dataset) > _MIN_ROWS


class DataProfileService:
    """Stateless service — call build_profile() with a raw tool result dict."""

    @staticmethod
    def build_profile(result: Any) -> Optional[Dict[str, Any]]:
        """Extract dataset from *result* and return a DataProfile dict.

        Returns ``None`` if the dataset is too small or extraction fails.
        """
        dataset = _extract_dataset(result)
        if not dataset or len(dataset) <= _MIN_ROWS:
            return None
        try:
            sample = dataset[:_SAMPLE_N]
            if _pd is not None:
                return _profile_with_pandas(dataset, sample)
            return _profile_pure_python(dataset, sample)
        except Exception as exc:
            logger.warning("DataProfileService.build_profile failed (non-blocking): %s", exc)
            return None


# ── Dataset extraction ───────────────────────────────────────────────────────

def _extract_dataset(result: Any) -> Optional[List[dict]]:
    """Find the first list-of-dicts in *result* (checks standard payload keys first)."""
    if not isinstance(result, dict):
        return None

    # Priority: standard MCP payload keys
    for key in ("dataset", "rows", "data", "items", "records", "result"):
        candidate = result.get(key)
        if _is_row_list(candidate):
            return candidate

    # Nested: output_data wrapper
    od = result.get("output_data")
    if isinstance(od, dict):
        for key in ("dataset", "rows", "data", "items", "records"):
            candidate = od.get(key)
            if _is_row_list(candidate):
                return candidate

    # Fallback: scan all top-level values
    for v in result.values():
        if _is_row_list(v):
            return v

    return None


def _is_row_list(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) > _MIN_ROWS
        and bool(v)
        and isinstance(v[0], dict)
    )


# ── Pandas-backed profiling ──────────────────────────────────────────────────

def _profile_with_pandas(dataset: List[dict], sample: List[dict]) -> Dict[str, Any]:
    df_full  = _pd.DataFrame(dataset)
    df_meta  = _pd.DataFrame(dataset[:_META_N])

    meta: Dict[str, Any] = {}
    for col in df_meta.columns:
        series = df_meta[col]
        meta[col] = {
            "dtype":        str(series.dtype),
            "null_count":   int(series.isna().sum()),
            "unique_count": int(series.nunique()),
        }

    stats: Dict[str, Any] = {}
    for col in df_full.select_dtypes(include="number").columns:
        s = df_full[col].dropna()
        if s.empty:
            continue
        stats[col] = {
            "min":  round(float(s.min()), 4),
            "max":  round(float(s.max()), 4),
            "mean": round(float(s.mean()), 4),
        }

    return {"sample": sample, "meta": meta, "stats": stats}


# ── Pure-Python fallback profiling ───────────────────────────────────────────

def _profile_pure_python(dataset: List[dict], sample: List[dict]) -> Dict[str, Any]:
    probe = dataset[:_META_N]
    if not probe:
        return {"sample": sample, "meta": {}, "stats": {}}

    all_keys: List[str] = list(probe[0].keys())

    meta: Dict[str, Any] = {}
    for col in all_keys:
        values = [row.get(col) for row in probe]
        null_count = sum(1 for v in values if v is None)
        unique_vals = set(str(v) for v in values if v is not None)
        dtype = _infer_dtype(values)
        meta[col] = {
            "dtype":        dtype,
            "null_count":   null_count,
            "unique_count": len(unique_vals),
        }

    stats: Dict[str, Any] = {}
    for col in all_keys:
        nums = [row.get(col) for row in dataset if isinstance(row.get(col), (int, float))]
        if len(nums) < 2:
            continue
        stats[col] = {
            "min":  round(min(nums), 4),
            "max":  round(max(nums), 4),
            "mean": round(sum(nums) / len(nums), 4),
        }

    return {"sample": sample, "meta": meta, "stats": stats}


def _infer_dtype(values: List[Any]) -> str:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "null"
    if all(isinstance(v, bool) for v in non_null):
        return "bool"
    if all(isinstance(v, int) for v in non_null):
        return "int"
    if all(isinstance(v, float) for v in non_null):
        return "float"
    if all(isinstance(v, (int, float)) for v in non_null):
        return "numeric"
    return "object"


# ── LLM injection text builder ───────────────────────────────────────────────

def build_profile_injection_text(profiles: List[Dict[str, Any]]) -> str:
    """Build compact text for injecting DataProfiles as hidden LLM context."""
    lines = [
        "以下為本次工具回傳資料的統計摘要（隱藏上下文，請勿向用戶顯示）：",
    ]
    for i, p in enumerate(profiles, 1):
        meta  = p.get("meta", {})
        stats = p.get("stats", {})
        n     = len(p.get("sample", []))
        cols  = list(meta.keys())
        lines.append(f"\n[DataProfile {i}]  欄位({len(cols)}): {cols}  |  樣本: {n} rows")
        for col, s in stats.items():
            lines.append(
                f"  {col}: min={s.get('min')}, max={s.get('max')}, mean={s.get('mean')}"
            )
        if not stats:
            lines.append("  （無數值欄位）")
    lines.append(
        "\n請根據上述 Schema 進行數據 Mapping 或 JIT 腳本生成，確保欄位名稱完全符合。"
    )
    return "\n".join(lines)
