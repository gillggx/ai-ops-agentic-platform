"""Utility processing tools (v15.3).

Tools: missing_value_impute, regex_extractor,
       diff_engine, cross_reference, logic_evaluator
"""
from __future__ import annotations

import math as _math
import re
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _jsonify, _safe_float


def _isnan(v) -> bool:
    """Safe isnan check for any value type."""
    try:
        return _math.isnan(float(v))
    except (TypeError, ValueError):
        return v is None


def missing_value_impute(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Fill missing values using mean, median, forward-fill, or a constant."""
    try:
        import numpy as np

        col = params.get("column")
        strategy = params.get("strategy", "mean").lower()
        fill_value = params.get("fill_value")

        cols_to_fill = [col] if col else None

        rows = [dict(r) for r in data]
        fill_log = []

        def _fill_col(c: str):
            vals = [row.get(c) for row in rows]
            nulls = [i for i, v in enumerate(vals) if v is None or (isinstance(v, float) and np.isnan(v))]
            if not nulls:
                return

            num_vals = [_safe_float(v) for v in vals if v is not None]
            num_vals = [v for v in num_vals if not np.isnan(v)]

            if strategy == "mean" and num_vals:
                replacement = float(np.mean(num_vals))
            elif strategy == "median" and num_vals:
                replacement = float(np.median(num_vals))
            elif strategy == "prev":
                replacement = None  # handled per-index
            elif fill_value is not None:
                replacement = fill_value
            else:
                replacement = 0

            for i in nulls:
                if strategy == "prev":
                    prev = next((rows[j].get(c) for j in range(i - 1, -1, -1)
                                 if rows[j].get(c) is not None), 0)
                    rows[i][c] = prev
                else:
                    rows[i][c] = replacement
            fill_log.append({"column": c, "filled": len(nulls), "strategy": strategy})

        if cols_to_fill:
            for c in cols_to_fill:
                _fill_col(c)
        else:
            for c in (rows[0].keys() if rows else []):
                _fill_col(c)

        total_filled = sum(f["filled"] for f in fill_log)
        return ToolResult.ok(
            f"Imputed {total_filled} missing values using strategy='{strategy}'",
            {"strategy": strategy, "fill_log": fill_log,
             "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"missing_value_impute failed: {exc}")


def regex_extractor(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Extract text using regex from a string column."""
    try:
        col = params.get("column")
        pattern = params.get("pattern")
        out_col = params.get("out_col", "extracted")

        if not (col and pattern):
            return ToolResult.err("'column' and 'pattern' params required.")

        compiled = re.compile(pattern)
        rows = []
        match_count = 0
        for row in data:
            val = str(row.get(col, ""))
            m = compiled.search(val)
            extracted = m.group(0) if m else None
            if extracted:
                match_count += 1
            rows.append({**row, out_col: extracted})

        return ToolResult.ok(
            f"Regex '{pattern}' on '{col}': matched {match_count}/{len(data)} rows",
            {"column": col, "pattern": pattern, "out_col": out_col,
             "match_count": match_count, "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"regex_extractor failed: {exc}")


def diff_engine(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Compare two JSON objects and return a diff of changed paths/values."""
    try:
        obj_a = params.get("obj_a", {})
        obj_b = params.get("obj_b", {})

        # If data is provided as two rows
        if not (obj_a and obj_b) and len(data) >= 2:
            obj_a, obj_b = data[0], data[1]

        def _flatten(d: Any, prefix: str = "") -> Dict[str, Any]:
            result = {}
            if isinstance(d, dict):
                for k, v in d.items():
                    result.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
            elif isinstance(d, list):
                for i, v in enumerate(d):
                    result.update(_flatten(v, f"{prefix}[{i}]"))
            else:
                result[prefix] = d
            return result

        flat_a = _flatten(obj_a)
        flat_b = _flatten(obj_b)
        all_keys = set(flat_a) | set(flat_b)

        diffs = []
        for key in sorted(all_keys):
            va = flat_a.get(key, "__missing__")
            vb = flat_b.get(key, "__missing__")
            if va != vb:
                diffs.append({"path": key, "before": va, "after": vb,
                              "change_type": "added" if va == "__missing__"
                              else "removed" if vb == "__missing__" else "modified"})

        return ToolResult.ok(
            f"Diff: {len(diffs)} change(s) found across {len(all_keys)} keys",
            {"total_keys": len(all_keys), "diff_count": len(diffs), "diffs": diffs},
        )
    except Exception as exc:
        return ToolResult.err(f"diff_engine failed: {exc}")


def cross_reference(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Join two datasets on a common key (inner/left join)."""
    try:
        import pandas as pd

        list_b = params.get("list_b", [])
        key = params.get("key")
        join_type = params.get("join_type", "inner")

        if not key:
            return ToolResult.err("'key' param required (common column name).")
        if not list_b:
            return ToolResult.err("'list_b' param required (second dataset as list-of-dicts).")

        df_a = pd.DataFrame(data)
        df_b = pd.DataFrame(list_b)

        merged = pd.merge(df_a, df_b, on=key, how=join_type, suffixes=("_a", "_b"))
        rows = merged.to_dict(orient="records")

        return ToolResult.ok(
            f"Cross-reference on '{key}' ({join_type} join): {len(data)} × {len(list_b)} → {len(rows)} rows",
            {"key": key, "join_type": join_type, "count_a": len(data),
             "count_b": len(list_b), "result_count": len(rows),
             "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"cross_reference failed: {exc}")


def logic_evaluator(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Evaluate a boolean expression with a safe whitelist context."""
    try:
        expression = params.get("expression", "")
        context = params.get("context", {})

        if not expression:
            return ToolResult.err("'expression' param required.")

        # Whitelist: only math/comparison operators, no builtins
        _FORBIDDEN = re.compile(r'\b(import|exec|eval|open|os|sys|subprocess|__)\b')
        if _FORBIDDEN.search(expression):
            return ToolResult.err("Expression contains forbidden keywords.")

        import math as _math
        safe_ns = {
            "math": _math, "abs": abs, "min": min, "max": max,
            "round": round, "len": len, "sum": sum,
            **context,
        }

        result = eval(expression, {"__builtins__": {}}, safe_ns)  # noqa: S307

        return ToolResult.ok(
            f"Expression '{expression}' → {result}",
            {"expression": expression, "result": result,
             "result_type": type(result).__name__},
        )
    except Exception as exc:
        return ToolResult.err(f"logic_evaluator failed: {exc}")


# ── NEW UTILITY / SPC TOOLS (v15.4) ───────────────────────────────────────────

def capability_analysis(data: list, **params) -> dict:
    """Process capability: Cp, Cpk, Pp, Ppk."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        usl = params.get("usl")
        lsl = params.get("lsl")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        if usl is None or lsl is None:
            return ToolResult.err("'usl' and 'lsl' required.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not _isnan(v)])
        n = len(arr)
        if n < 2:
            return ToolResult.err("Need at least 2 data points.")
        usl, lsl = float(usl), float(lsl)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        std_overall = float(np.std(arr, ddof=0)) or 1e-9
        std = std or 1e-9
        cp = (usl - lsl) / (6 * std)
        cpu = (usl - mean) / (3 * std)
        cpl = (mean - lsl) / (3 * std)
        cpk = min(cpu, cpl)
        pp = (usl - lsl) / (6 * std_overall)
        ppk = min((usl - mean) / (3 * std_overall), (mean - lsl) / (3 * std_overall))
        out_of_spec = int(np.sum((arr < lsl) | (arr > usl)))
        return ToolResult.ok(
            f"Capability '{value_col}': Cp={cp:.3f}, Cpk={cpk:.3f}, "
            f"Pp={pp:.3f}, Ppk={ppk:.3f}, out-of-spec={out_of_spec}/{n}",
            {"column": value_col, "n": n, "usl": usl, "lsl": lsl,
             "mean": round(mean, 6), "std_within": round(float(np.std(arr, ddof=1)), 6),
             "Cp": round(cp, 4), "Cpk": round(cpk, 4),
             "Pp": round(pp, 4), "Ppk": round(ppk, 4),
             "out_of_spec": out_of_spec, "out_of_spec_pct": round(out_of_spec / n * 100, 2)},
        )
    except Exception as exc:
        return ToolResult.err(f"capability_analysis failed: {exc}")


def western_electric_rules(data: list, **params) -> dict:
    """Check 8 Western Electric SPC rules."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not _isnan(v)])
        n = len(arr)
        cl = float(params.get("cl", np.mean(arr)))
        sigma = float(np.std(arr, ddof=1)) or 1.0
        ucl = float(params.get("ucl", cl + 3 * sigma))
        lcl = float(params.get("lcl", cl - 3 * sigma))
        z = (arr - cl) / sigma
        violations = []
        # Rule 1: 1 point beyond 3σ
        r1 = [i for i in range(n) if abs(z[i]) > 3]
        if r1:
            violations.append({"rule": 1, "desc": "1 point beyond 3σ", "indices": r1[:20]})
        # Rule 2: 9 consecutive on same side
        for i in range(n - 8):
            if all(z[i:i+9] > 0) or all(z[i:i+9] < 0):
                violations.append({"rule": 2, "desc": "9 consecutive same side", "indices": list(range(i, i+9))})
                break
        # Rule 3: 6 consecutive increasing/decreasing
        for i in range(n - 5):
            if all(arr[i+j] < arr[i+j+1] for j in range(5)) or all(arr[i+j] > arr[i+j+1] for j in range(5)):
                violations.append({"rule": 3, "desc": "6 consecutive trend", "indices": list(range(i, i+6))})
                break
        # Rule 4: 14 alternating up/down
        for i in range(n - 13):
            alt = all((arr[i+j+1] - arr[i+j]) * (arr[i+j+2] - arr[i+j+1]) < 0 for j in range(12))
            if alt:
                violations.append({"rule": 4, "desc": "14 alternating", "indices": list(range(i, i+14))})
                break
        # Rule 5: 2 of 3 beyond 2σ same side
        for i in range(n - 2):
            sub = z[i:i+3]
            if sum(1 for s in sub if s > 2) >= 2 or sum(1 for s in sub if s < -2) >= 2:
                violations.append({"rule": 5, "desc": "2 of 3 beyond 2σ", "indices": list(range(i, i+3))})
                break
        # Rule 6: 4 of 5 beyond 1σ same side
        for i in range(n - 4):
            sub = z[i:i+5]
            if sum(1 for s in sub if s > 1) >= 4 or sum(1 for s in sub if s < -1) >= 4:
                violations.append({"rule": 6, "desc": "4 of 5 beyond 1σ", "indices": list(range(i, i+5))})
                break
        # Rule 7: 15 within 1σ
        for i in range(n - 14):
            if all(abs(z[i+j]) < 1 for j in range(15)):
                violations.append({"rule": 7, "desc": "15 within 1σ (stratification)", "indices": list(range(i, i+15))})
                break
        # Rule 8: 8 beyond 1σ (no points in zone C)
        for i in range(n - 7):
            if all(abs(z[i+j]) > 1 for j in range(8)):
                violations.append({"rule": 8, "desc": "8 beyond 1σ (mixture)", "indices": list(range(i, i+8))})
                break
        return ToolResult.ok(
            f"Western Electric Rules '{value_col}': {len(violations)} rule violation(s)",
            {"column": value_col, "n": n, "cl": round(cl, 4), "ucl": round(ucl, 4),
             "lcl": round(lcl, 4), "sigma": round(sigma, 4),
             "n_violations": len(violations), "violations": violations},
        )
    except Exception as exc:
        return ToolResult.err(f"western_electric_rules failed: {exc}")


def nelson_rules(data: list, **params) -> dict:
    """Nelson SPC rules 1-8."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not _isnan(v)])
        n = len(arr)
        mean_val = float(params.get("mean", np.mean(arr)))
        std_val = float(params.get("std", np.std(arr, ddof=1))) or 1.0
        z = (arr - mean_val) / std_val
        violations = []
        # Rule 1: outside 3σ
        r1 = [i for i in range(n) if abs(z[i]) > 3]
        if r1:
            violations.append({"rule": 1, "desc": "Outside 3σ", "indices": r1[:20]})
        # Rule 2: 9 on same side
        for i in range(n - 8):
            if all(z[i:i+9] > 0) or all(z[i:i+9] < 0):
                violations.append({"rule": 2, "desc": "9 on same side of mean", "indices": list(range(i, i+9))})
                break
        # Rule 3: 6 consecutive monotone
        for i in range(n - 5):
            if all(arr[i+j] < arr[i+j+1] for j in range(5)) or all(arr[i+j] > arr[i+j+1] for j in range(5)):
                violations.append({"rule": 3, "desc": "6 monotone", "indices": list(range(i, i+6))})
                break
        # Rule 4: 14 alternating
        for i in range(n - 13):
            alt = all((arr[i+j+1] - arr[i+j]) * (arr[i+j+2] - arr[i+j+1]) < 0 for j in range(12))
            if alt:
                violations.append({"rule": 4, "desc": "14 alternating", "indices": list(range(i, i+14))})
                break
        # Rule 5: 2 of 3 > 2σ same side
        for i in range(n - 2):
            sub = z[i:i+3]
            if sum(1 for s in sub if s > 2) >= 2 or sum(1 for s in sub if s < -2) >= 2:
                violations.append({"rule": 5, "desc": "2 of 3 beyond 2σ", "indices": list(range(i, i+3))})
                break
        # Rule 6: 4 of 5 > 1σ same side
        for i in range(n - 4):
            sub = z[i:i+5]
            if sum(1 for s in sub if s > 1) >= 4 or sum(1 for s in sub if s < -1) >= 4:
                violations.append({"rule": 6, "desc": "4 of 5 beyond 1σ", "indices": list(range(i, i+5))})
                break
        # Rule 7: 15 within 1σ
        for i in range(n - 14):
            if all(abs(z[i+j]) < 1 for j in range(15)):
                violations.append({"rule": 7, "desc": "15 within 1σ", "indices": list(range(i, i+15))})
                break
        # Rule 8: 8 outside 1σ
        for i in range(n - 7):
            if all(abs(z[i+j]) > 1 for j in range(8)):
                violations.append({"rule": 8, "desc": "8 outside 1σ", "indices": list(range(i, i+8))})
                break
        return ToolResult.ok(
            f"Nelson Rules '{value_col}': {len(violations)} violation(s)",
            {"column": value_col, "n": n, "mean": round(mean_val, 4), "std": round(std_val, 4),
             "n_violations": len(violations), "violations": violations},
        )
    except Exception as exc:
        return ToolResult.err(f"nelson_rules failed: {exc}")


def process_sigma(data: list, **params) -> dict:
    """DPMO and sigma level calculation."""
    try:
        import numpy as np
        import math as _m
        defects_col = params.get("defects_col")
        opportunities = int(params.get("opportunities_per_unit", 1))
        if not defects_col:
            sample = data[0] if data else {}
            defects_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not defects_col:
            return ToolResult.err("No numeric column found.")
        total_defects = sum(_safe_float(row.get(defects_col, 0)) for row in data)
        total_units = len(data)
        total_opportunities = total_units * opportunities
        dpmo = (total_defects / total_opportunities * 1_000_000) if total_opportunities > 0 else 0.0
        # Sigma level from DPMO using inverse normal approximation
        if dpmo <= 0:
            sigma_level = 6.0
        elif dpmo >= 1_000_000:
            sigma_level = 0.0
        else:
            p = dpmo / 1_000_000
            # Box-Muller approximation for sigma level
            z = _m.sqrt(-2 * _m.log(p)) if p < 1 else 0.0
            sigma_level = max(0.0, z + 1.5)  # add 1.5σ shift
        return ToolResult.ok(
            f"Process sigma '{defects_col}': DPMO={dpmo:.0f}, sigma={sigma_level:.2f}",
            {"defects_col": defects_col, "total_defects": int(total_defects),
             "total_units": total_units, "opportunities_per_unit": opportunities,
             "total_opportunities": total_opportunities,
             "dpmo": round(dpmo, 2), "sigma_level": round(sigma_level, 3),
             "yield_pct": round((1 - dpmo / 1_000_000) * 100, 4)},
        )
    except Exception as exc:
        return ToolResult.err(f"process_sigma failed: {exc}")


def gage_repeatability(data: list, **params) -> dict:
    """Measurement repeatability using range method (Gage R&R)."""
    try:
        import numpy as np
        meas_col = params.get("measurement_col")
        part_col = params.get("part_col")
        operator_col = params.get("operator_col")
        if not (meas_col and part_col):
            return ToolResult.err("'measurement_col' and 'part_col' required.")
        # Group by part and operator
        groups = {}
        for row in data:
            part = str(row.get(part_col, ""))
            op = str(row.get(operator_col, "all")) if operator_col else "all"
            v = _safe_float(row.get(meas_col))
            if not _isnan(v):
                groups.setdefault((part, op), []).append(v)
        ranges = [max(vs) - min(vs) for vs in groups.values() if len(vs) > 1]
        if not ranges:
            return ToolResult.err("Need repeated measurements per part/operator.")
        R_bar = float(np.mean(ranges))
        # d2 constant for subgroup size 2
        d2 = 1.128
        sigma_repeatability = R_bar / d2
        n_parts = len({k[0] for k in groups})
        n_ops = len({k[1] for k in groups})
        return ToolResult.ok(
            f"Gage repeatability '{meas_col}': R̄={R_bar:.4f}, σ_repeat={sigma_repeatability:.4f}",
            {"measurement_col": meas_col, "part_col": part_col, "operator_col": operator_col,
             "n_parts": n_parts, "n_operators": n_ops,
             "mean_range": round(R_bar, 6),
             "sigma_repeatability": round(sigma_repeatability, 6),
             "estimated_ev": round(sigma_repeatability * 6, 4)},
        )
    except Exception as exc:
        return ToolResult.err(f"gage_repeatability failed: {exc}")


def tolerance_interval(data: list, **params) -> dict:
    """Two-sided 95%/95% tolerance interval (normal assumption)."""
    try:
        import numpy as np
        import math as _m
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not _isnan(v)])
        n = len(arr)
        if n < 2:
            return ToolResult.err("Need at least 2 data points.")
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        # K factor for 95%/95% tolerance interval (approximation)
        # Using Howe approximation
        alpha, p = 0.05, 0.95
        z_p = 1.6449  # z for 95th percentile
        chi2_alpha = n - 1  # rough approximation; chi2 at alpha
        k = _m.sqrt((n - 1) * (1 + 1/n) * z_p**2 / chi2_alpha) if chi2_alpha > 0 else z_p
        k = max(k, 2.0)
        ti_lower = mean - k * std
        ti_upper = mean + k * std
        return ToolResult.ok(
            f"95%/95% tolerance interval '{value_col}' (n={n}): "
            f"[{ti_lower:.4f}, {ti_upper:.4f}]",
            {"column": value_col, "n": n, "mean": round(mean, 6), "std": round(std, 6),
             "k_factor": round(k, 4),
             "tolerance_lower": round(ti_lower, 6), "tolerance_upper": round(ti_upper, 6),
             "interval_width": round(ti_upper - ti_lower, 6)},
        )
    except Exception as exc:
        return ToolResult.err(f"tolerance_interval failed: {exc}")


def control_limits_calculator(data: list, **params) -> dict:
    """Compute UCL/LCL from data using 3-sigma or custom method."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        method = params.get("method", "3sigma")
        n_subgroups = params.get("n_subgroups")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not _isnan(v)])
        n = len(arr)
        if n < 2:
            return ToolResult.err("Need at least 2 data points.")
        cl = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        if method == "3sigma":
            sigma_mult = 3.0
        elif method == "2sigma":
            sigma_mult = 2.0
        else:
            sigma_mult = float(method.replace("sigma", "")) if "sigma" in str(method) else 3.0
        # If subgroup size given, use MR-based estimate for individuals chart
        if n_subgroups and int(n_subgroups) > 1:
            sg = int(n_subgroups)
            subgroup_ranges = [float(np.ptp(arr[i:i+sg])) for i in range(0, n - sg + 1, sg)]
            if subgroup_ranges:
                r_bar = float(np.mean(subgroup_ranges))
                d2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326}.get(sg, 2.326)
                std = r_bar / d2
        ucl = cl + sigma_mult * std
        lcl = cl - sigma_mult * std
        out_of_control = int(np.sum((arr > ucl) | (arr < lcl)))
        return ToolResult.ok(
            f"Control limits '{value_col}' ({method}): CL={cl:.4f}, UCL={ucl:.4f}, LCL={lcl:.4f}, "
            f"OOC={out_of_control}/{n}",
            {"column": value_col, "n": n, "method": method,
             "cl": round(cl, 6), "ucl": round(ucl, 6), "lcl": round(lcl, 6),
             "sigma": round(std, 6), "out_of_control": out_of_control},
        )
    except Exception as exc:
        return ToolResult.err(f"control_limits_calculator failed: {exc}")


def top_n_contributors(data: list, **params) -> dict:
    """Rank groups by contribution to total."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        top_n = int(params.get("top_n", 10))
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not _isnan(v):
                groups[g] = groups.get(g, 0.0) + v
        total = sum(groups.values())
        ranked = sorted(groups.items(), key=lambda x: -abs(x[1]))[:top_n]
        cumulative = 0.0
        results = []
        for rank, (g, val) in enumerate(ranked, 1):
            pct = val / total * 100 if total != 0 else 0.0
            cumulative += pct
            results.append({"rank": rank, "group": g, "value": round(val, 4),
                            "pct": round(pct, 2), "cumulative_pct": round(cumulative, 2)})
        return ToolResult.ok(
            f"Top-{top_n} contributors '{value_col}' by '{group_col}': "
            f"top={results[0]['group']} ({results[0]['pct']}%)",
            {"value_col": value_col, "group_col": group_col, "total": round(total, 4),
             "top_n": top_n, "contributors": results},
        )
    except Exception as exc:
        return ToolResult.err(f"top_n_contributors failed: {exc}")


def within_between_variance(data: list, **params) -> dict:
    """Decompose total variance into within-group and between-group components."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not _isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        all_vals = np.concatenate([np.array(v) for v in groups.values()])
        grand_mean = float(np.mean(all_vals))
        total_n = len(all_vals)
        ss_between = sum(len(v) * (float(np.mean(v)) - grand_mean) ** 2 for v in groups.values())
        ss_within = sum(float(np.sum((np.array(v) - np.mean(v)) ** 2)) for v in groups.values())
        ss_total = float(np.sum((all_vals - grand_mean) ** 2))
        pct_between = ss_between / ss_total * 100 if ss_total > 0 else 0.0
        pct_within = ss_within / ss_total * 100 if ss_total > 0 else 0.0
        icc = pct_between / 100  # intraclass correlation coefficient
        return ToolResult.ok(
            f"Variance decomposition '{value_col}' by '{group_col}': "
            f"between={pct_between:.1f}%, within={pct_within:.1f}%, ICC={icc:.3f}",
            {"value_col": value_col, "group_col": group_col,
             "n_groups": len(groups), "total_n": total_n,
             "ss_total": round(ss_total, 4), "ss_between": round(ss_between, 4),
             "ss_within": round(ss_within, 4),
             "pct_between": round(pct_between, 2), "pct_within": round(pct_within, 2),
             "icc": round(icc, 4)},
        )
    except Exception as exc:
        return ToolResult.err(f"within_between_variance failed: {exc}")


def data_quality_score(data: list, **params) -> dict:
    """Score columns: completeness, uniqueness, and range check."""
    try:
        import numpy as np
        columns = params.get("columns")
        n = len(data)
        if n == 0:
            return ToolResult.err("No data provided.")
        if not columns and data:
            columns = list(data[0].keys())
        results = []
        for col in columns:
            vals = [row.get(col) for row in data]
            null_count = sum(1 for v in vals if v is None or (isinstance(v, float) and _isnan(v)))
            completeness = round((n - null_count) / n * 100, 2)
            non_null = [v for v in vals if v is not None]
            unique_count = len(set(str(v) for v in non_null))
            uniqueness = round(unique_count / n * 100, 2) if n > 0 else 0.0
            num_vals = [_safe_float(v) for v in non_null]
            num_vals = [v for v in num_vals if not _isnan(v)]
            range_check = {}
            if num_vals:
                range_check = {
                    "min": round(float(min(num_vals)), 4),
                    "max": round(float(max(num_vals)), 4),
                    "mean": round(float(np.mean(num_vals)), 4),
                }
            score = round((completeness * 0.5 + min(uniqueness, 100) * 0.3 + 20) / 100, 3)
            score = min(score, 1.0)
            results.append({"column": col, "completeness_pct": completeness,
                            "uniqueness_pct": uniqueness, "null_count": null_count,
                            "unique_count": unique_count, "quality_score": score,
                            **range_check})
        overall = round(float(np.mean([r["quality_score"] for r in results])), 3)
        return ToolResult.ok(
            f"Data quality score ({len(columns)} columns, n={n}): overall={overall}",
            {"n_rows": n, "n_columns": len(columns), "overall_quality": overall,
             "column_scores": results},
        )
    except Exception as exc:
        return ToolResult.err(f"data_quality_score failed: {exc}")


# Helper alias for math.isnan used in utility functions
def _isnan(v):
    import math
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return v is None
