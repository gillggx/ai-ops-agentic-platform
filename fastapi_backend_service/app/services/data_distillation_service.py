"""Data Distillation Service — v14.1 Diagnostic Fingerprinting.

Architecture (PRD v14 §3 upgrade):
  DistilledSchema = {summary, anomalies, raw_sample, assertions}
  DataAnalyzer    = Pandas stats engine (anomaly detection + Nelson rules)
  DataDescriptor  = Converts raw stats → human-readable diagnostic assertions

Key rules:
  - Dataset > 20 rows → force distillation; LLM never sees raw rows
  - ui_render_payload (full data) preserved in output_data for frontend
  - llm_context_payload (compact) replaces llm_readable_data for LLM
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DISTILL_MIN_ROWS = 20  # PRD spec: strictly enforce 20-row threshold


# ── DistilledSchema dataclass (plain dict for JSON-serializability) ────────────

def _make_distilled_schema(
    summary: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    raw_sample: List[Dict[str, Any]],
    assertions: List[str],
) -> Dict[str, Any]:
    """Build the canonical DistilledSchema returned to the LLM."""
    return {
        "summary": summary,       # Count, Avg, Std, Max, Min, Cp/Cpk, OOC rate
        "anomalies": anomalies,   # Rows violating UCL/LCL + Nelson rule hits
        "raw_sample": raw_sample, # First 5 rows for context
        "assertions": assertions, # Human-readable diagnostic fingerprint lines
        "_distillation": "v14.1_diagnostic_fingerprint",
    }


# ── Main Service ───────────────────────────────────────────────────────────────

class DataDistillationService:
    """Distils large MCP datasets into DistilledSchema for the LLM.

    Separates:
      llm_context_payload  → compact DistilledSchema (injected into llm_readable_data)
      ui_render_payload    → full dataset preserved in output_data (for frontend charts)
    """

    async def distill_mcp_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Entry point. Returns result with llm_readable_data replaced by DistilledSchema."""
        try:
            od = result.get("output_data") or {}
            dataset = od.get("dataset") or []

            if not isinstance(dataset, list) or len(dataset) < _DISTILL_MIN_ROWS:
                return result  # Small dataset — pass through unchanged

            analyzer = DataAnalyzer(dataset)
            summary   = analyzer.compute_summary()
            anomalies = analyzer.detect_anomalies()
            raw_sample = dataset[:5]
            assertions = DataDescriptor.generate_assertions(summary, anomalies, dataset)

            distilled = _make_distilled_schema(summary, anomalies, raw_sample, assertions)

            # Replace llm_readable_data with compact distilled schema
            # ui_render_payload (output_data) is untouched — full data for frontend
            return {
                **result,
                "llm_readable_data": distilled,
            }

        except Exception as exc:
            logger.warning("DataDistillationService failed (passthrough): %s", exc)
            return result


# ── DataAnalyzer ──────────────────────────────────────────────────────────────

class DataAnalyzer:
    """Pandas-powered statistical engine. Falls back to pure Python if unavailable."""

    def __init__(self, dataset: List[Dict[str, Any]]) -> None:
        self._dataset = dataset
        self._df: Optional[Any] = None
        try:
            import pandas as pd
            self._df = pd.DataFrame(dataset)
        except Exception:
            pass

    # ── Summary ───────────────────────────────────────────────────────────────

    def compute_summary(self) -> Dict[str, Any]:
        if self._df is not None:
            return self._pandas_summary()
        return self._python_summary()

    def _pandas_summary(self) -> Dict[str, Any]:
        df = self._df
        n = len(df)
        summary: Dict[str, Any] = {"row_count": n, "columns": list(df.columns)}

        # Numeric stats (cap at 8 cols)
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            desc = df[numeric_cols].describe()
            ns: Dict[str, Any] = {}
            for col in numeric_cols[:8]:
                s = {"count": int(desc.loc["count", col]),
                     "mean":  round(float(desc.loc["mean", col]), 4),
                     "std":   round(float(desc.loc["std",  col]), 4),
                     "min":   round(float(desc.loc["min",  col]), 4),
                     "max":   round(float(desc.loc["max",  col]), 4)}
                # Cp/Cpk if UCL/LCL columns detected for this value col
                ucl = self._detect_control_limit(col, "ucl")
                lcl = self._detect_control_limit(col, "lcl")
                if ucl is not None and lcl is not None and s["std"] > 0:
                    spec_range = ucl - lcl
                    cp  = round(spec_range / (6 * s["std"]), 4)
                    cpk = round(min(ucl - s["mean"], s["mean"] - lcl) / (3 * s["std"]), 4)
                    s["Cp"] = cp
                    s["Cpk"] = cpk
                    s["UCL"] = ucl
                    s["LCL"] = lcl
                ns[col] = s
            summary["numeric_stats"] = ns

        # OOC flag column
        ooc_col = self._find_ooc_col()
        if ooc_col:
            ooc_series = df[ooc_col].astype(str).str.upper().isin({"TRUE", "1", "YES", "OOC", "ABNORMAL"})
            ooc_n = int(ooc_series.sum())
            summary["ooc_count"]    = ooc_n
            summary["ooc_rate_pct"] = round(ooc_n / n * 100, 2) if n > 0 else 0
            summary["max_consecutive_ooc"] = _max_consecutive_run(ooc_series.tolist())

        # Categorical stats (tool/lot breakdowns)
        cat_cols = [c for c in df.select_dtypes(include="object").columns
                    if any(k in c.lower() for k in ("tool", "lot", "recipe", "status", "dcitem", "chartname"))]
        for col in cat_cols[:4]:
            vc = df[col].value_counts().head(5).to_dict()
            summary.setdefault("categorical_stats", {})[col] = {str(k): int(v) for k, v in vc.items()}

        return summary

    def _python_summary(self) -> Dict[str, Any]:
        dataset = self._dataset
        n = len(dataset)
        summary: Dict[str, Any] = {"row_count": n}
        if not dataset or not isinstance(dataset[0], dict):
            return summary
        summary["columns"] = list(dataset[0].keys())
        ns: Dict[str, Any] = {}
        for key in list(dataset[0].keys())[:8]:
            vals = [r.get(key) for r in dataset if isinstance(r.get(key), (int, float))]
            if len(vals) > 1:
                avg = sum(vals) / len(vals)
                ns[key] = {"count": len(vals), "mean": round(avg, 4),
                            "min": min(vals), "max": max(vals),
                            "std": round((_variance(vals)) ** 0.5, 4)}
        if ns:
            summary["numeric_stats"] = ns
        return summary

    # ── Anomaly Detection ─────────────────────────────────────────────────────

    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Return anomaly list with source ('ucl_lcl' | 'nelson_rule_N')."""
        anomalies: List[Dict[str, Any]] = []
        if self._df is not None:
            anomalies.extend(self._ucl_lcl_violations())
            anomalies.extend(self._nelson_rules())
        else:
            anomalies.extend(self._python_ucl_lcl())
        return anomalies

    def _ucl_lcl_violations(self) -> List[Dict[str, Any]]:
        df = self._df
        results = []
        value_col = self._find_value_col()
        ucl_val = self._detect_control_limit(value_col or "", "ucl") if value_col else None
        lcl_val = self._detect_control_limit(value_col or "", "lcl") if value_col else None
        if value_col and ucl_val is not None and lcl_val is not None:
            mask = (df[value_col] > ucl_val) | (df[value_col] < lcl_val)
            violating = df[mask].head(10)
            for idx, row in violating.iterrows():
                results.append({
                    "source": "ucl_lcl",
                    "row_index": int(idx),
                    "value": round(float(row[value_col]), 4),
                    "UCL": ucl_val,
                    "LCL": lcl_val,
                    "direction": "above_UCL" if float(row[value_col]) > ucl_val else "below_LCL",
                    "record": {k: (float(v) if hasattr(v, 'item') else v)
                               for k, v in row.items() if k in self._key_cols()},
                })
        return results

    def _nelson_rules(self) -> List[Dict[str, Any]]:
        """Nelson Rule 2 (7+ same side) and Rule 3 (6+ monotone trend)."""
        df = self._df
        results = []
        value_col = self._find_value_col()
        if not value_col or value_col not in df.columns:
            return results
        vals = df[value_col].tolist()
        mean_val = sum(vals) / len(vals)

        # Rule 2: 7+ consecutive on same side of mean
        run_len, run_start, run_side = 0, 0, None
        for i, v in enumerate(vals):
            side = "above" if v > mean_val else "below"
            if side == run_side:
                run_len += 1
            else:
                run_len, run_start, run_side = 1, i, side
            if run_len >= 7:
                results.append({
                    "source": "nelson_rule_2",
                    "rule": "7+ consecutive points on same side of mean",
                    "start_index": run_start,
                    "length": run_len,
                    "side": run_side,
                    "mean": round(mean_val, 4),
                })
                break  # report once per rule

        # Rule 3: 6+ monotone trend
        trend_len, trend_start, trend_dir = 1, 0, None
        for i in range(1, len(vals)):
            d = "up" if vals[i] > vals[i-1] else ("down" if vals[i] < vals[i-1] else trend_dir)
            if d == trend_dir:
                trend_len += 1
            else:
                trend_len, trend_start, trend_dir = 2, i-1, d
            if trend_len >= 6:
                results.append({
                    "source": "nelson_rule_3",
                    "rule": "6+ consecutive monotone trend",
                    "start_index": trend_start,
                    "length": trend_len,
                    "direction": trend_dir,
                })
                break

        return results

    def _python_ucl_lcl(self) -> List[Dict[str, Any]]:
        dataset = self._dataset
        results = []
        first = dataset[0] if dataset else {}
        ucl_key = next((k for k in first if "ucl" in k.lower()), None)
        lcl_key = next((k for k in first if "lcl" in k.lower()), None)
        val_key = next((k for k in first if k.lower() in ("value", "val", "measurement")), None)
        if not (ucl_key and lcl_key and val_key):
            return results
        for i, row in enumerate(dataset[:50]):
            v, ucl, lcl = row.get(val_key), row.get(ucl_key), row.get(lcl_key)
            if None not in (v, ucl, lcl) and (v > ucl or v < lcl):
                results.append({"source": "ucl_lcl", "row_index": i,
                                 "value": v, "UCL": ucl, "LCL": lcl})
        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_value_col(self) -> Optional[str]:
        if self._df is None:
            return None
        numeric_cols = self._df.select_dtypes(include="number").columns.tolist()
        preferred = ["value", "val", "measurement", "cd", "depth"]
        for p in preferred:
            match = next((c for c in numeric_cols if c.lower() == p), None)
            if match:
                return match
        # Exclude UCL/LCL/Mean columns
        return next((c for c in numeric_cols
                     if not any(k in c.lower() for k in ("ucl", "lcl", "mean", "cl", "limit"))), None)

    def _find_ooc_col(self) -> Optional[str]:
        if self._df is None:
            return None
        return next((c for c in self._df.columns
                     if c.lower() in ("is_ooc", "ooc", "is_abnormal", "abnormal", "status")), None)

    def _detect_control_limit(self, value_col: str, limit_type: str) -> Optional[float]:
        """Find UCL or LCL value from a sibling column or constant."""
        if self._df is None:
            return None
        # Look for a column that's constant (all same value) named like UCL/LCL
        for col in self._df.columns:
            if limit_type in col.lower():
                try:
                    unique = self._df[col].dropna().unique()
                    if len(unique) == 1:
                        return float(unique[0])
                    # Multiple values — use mean as representative
                    return float(self._df[col].mean())
                except Exception:
                    pass
        return None

    def _key_cols(self) -> List[str]:
        if self._df is None:
            return []
        preferred = ["tool", "toolid", "tool_id", "lotid", "lot_id", "datetime", "timestamp"]
        return [c for c in self._df.columns if any(p in c.lower() for p in preferred)][:4]


# ── DataDescriptor ─────────────────────────────────────────────────────────────

class DataDescriptor:
    """Converts raw stats into human-readable diagnostic assertions (fingerprints).

    Turns:
      mean=45.039, UCL=46.5, LCL=43.5  →  「平均值 45.039（正常，接近中心線 45.0）」
      nelson_rule_2 side=above, len=9   →  「連續 9 點高於均值，疑似系統性正偏移」
      tool TETCH01: 8/10 anomalies      →  「機台 TETCH01 貢獻 80% 的異常點，建議優先排查」
    """

    @staticmethod
    def generate_assertions(
        summary: Dict[str, Any],
        anomalies: List[Dict[str, Any]],
        dataset: List[Dict[str, Any]],
    ) -> List[str]:
        assertions: List[str] = []

        ns = summary.get("numeric_stats", {})
        value_col_stats = next(
            ((col, s) for col, s in ns.items()
             if not any(k in col.lower() for k in ("ucl", "lcl", "mean", "cl", "limit"))),
            None,
        )

        # ── 1. Process capability ──────────────────────────────────────────────
        if value_col_stats:
            col, s = value_col_stats
            ucl = s.get("UCL")
            lcl = s.get("LCL")
            mean = s.get("mean", 0)
            cp  = s.get("Cp")
            cpk = s.get("Cpk")
            if ucl is not None and lcl is not None:
                center = (ucl + lcl) / 2
                if mean > center * 1.02:
                    bias = "正偏移（偏高）"
                elif mean < center * 0.98:
                    bias = "負偏移（偏低）"
                else:
                    bias = "接近中心線"
                assertions.append(
                    f"【{col}】平均值 {mean}，{bias}；UCL={ucl}，LCL={lcl}"
                )
            if cp is not None and cpk is not None:
                capability = "製程能力充足" if cpk >= 1.33 else ("邊緣" if cpk >= 1.0 else "製程能力不足⚠️")
                assertions.append(f"製程能力：Cp={cp}，Cpk={cpk}，{capability}")

        # ── 2. OOC rate ────────────────────────────────────────────────────────
        ooc_count = summary.get("ooc_count")
        ooc_rate  = summary.get("ooc_rate_pct")
        if ooc_count is not None:
            if ooc_count == 0:
                assertions.append("OOC 點位：0（全部在管制內）")
            else:
                max_run = summary.get("max_consecutive_ooc", 0)
                msg = f"OOC 點位：{ooc_count} 筆（{ooc_rate}%）"
                if max_run >= 3:
                    msg += f"，最長連續 OOC 串 = {max_run} 點"
                assertions.append(msg)

        # ── 3. Nelson rule hits ────────────────────────────────────────────────
        for a in anomalies:
            src = a.get("source", "")
            if src == "nelson_rule_2":
                assertions.append(
                    f"⚠️ Nelson Rule 2：連續 {a['length']} 點{'高' if a['side']=='above' else '低'}於均值 {a['mean']}，"
                    "疑似系統性偏移或機台漂移，建議確認校正記錄。"
                )
            elif src == "nelson_rule_3":
                dir_zh = "上升" if a.get("direction") == "up" else "下降"
                assertions.append(
                    f"⚠️ Nelson Rule 3：連續 {a['length']} 點單調{dir_zh}趨勢，"
                    "疑似機台磨耗或緩慢漂移，建議確認 PM 週期。"
                )

        # ── 4. Equipment hotspot ───────────────────────────────────────────────
        cat = summary.get("categorical_stats", {})
        tool_col = next((k for k in cat if any(t in k.lower() for t in ("tool", "toolid"))), None)
        if tool_col and anomalies:
            # Count anomalies per tool
            tool_anomaly_count: Dict[str, int] = {}
            for a in anomalies:
                rec = a.get("record", {})
                tool_val = str(rec.get(tool_col, rec.get("tool", rec.get("toolid", ""))))
                if tool_val:
                    tool_anomaly_count[tool_val] = tool_anomaly_count.get(tool_val, 0) + 1
            if tool_anomaly_count:
                top_tool = max(tool_anomaly_count, key=lambda k: tool_anomaly_count[k])
                top_cnt  = tool_anomaly_count[top_tool]
                total_anomalies = len(anomalies)
                pct = round(top_cnt / total_anomalies * 100)
                assertions.append(
                    f"機台 Hotspot：{top_tool} 貢獻 {top_cnt}/{total_anomalies} 異常點（{pct}%），建議優先排查。"
                )

        return assertions


# ── Pure Python helpers ────────────────────────────────────────────────────────

def _max_consecutive_run(flags: List[bool]) -> int:
    max_run = current = 0
    for f in flags:
        current = (current + 1) if f else 0
        max_run = max(max_run, current)
    return max_run


def _variance(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    avg = sum(vals) / len(vals)
    return sum((v - avg) ** 2 for v in vals) / (len(vals) - 1)
