"""Mock Data Router — semiconductor KPI mock APIs for testing.

Five endpoints (PRD §2.2):
- GET /mock/apc         : APC data (lot_id, operation_number)
- GET /mock/recipe      : Recipe data with dynamic 12-hour-ago timestamp
- GET /mock/ec          : Equipment Constants (tool_id)
- GET /mock/spc         : SPC Chart Data (CD measurement, 100 records, optional tool_id filter)
- GET /mock/apc_tuning  : APC Tuning Values (etchTime per lot, dynamic 1-hour-ago base, optional apc_name filter)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/mock", tags=["mock-data"])


@router.get("/apc", summary="APC Mock Data")
async def get_apc(
    lot_id: str = Query(..., description="Lot ID"),
    operation_number: str = Query("3200", description="Operation number (default: 3200)"),
):
    """Return mock APC control data for a given lot and operation."""
    seed = hash(lot_id + operation_number) % 1000

    _apc_names = [
        "TETCH01_CD_Control",
        "TETCH02_CD_Control",
        "TETCH03_RCD_Control",
        "POLY01_CD_Control",
    ]
    _model_names = [
        "Etch_CD_EWMA_v2.1",
        "Etch_CD_EWMA_v3.0",
        "RCD_EWMA_v1.5",
        "Poly_CD_EWMA_v2.0",
    ]

    now = datetime.now(timezone.utc)
    model_update_time = now - timedelta(days=14)
    param_update_time = now - timedelta(hours=2)

    parameters = [
        {
            "name": "CHF3_Gas_Offset",
            "value": round(2.5 + (seed % 10) / 10.0 - 0.5, 2),
            "update_time": param_update_time.isoformat(),
        },
        {
            "name": "RF_Power_Delta",
            "value": -10 + (seed % 5) - 2,
            "update_time": param_update_time.isoformat(),
        },
    ]

    return {
        "lot_id": lot_id,
        "operation_number": operation_number,
        "apc_name": _apc_names[seed % len(_apc_names)],
        "apc_model_name": _model_names[seed % len(_model_names)],
        "model_update_time": model_update_time.isoformat(),
        "parameters": parameters,
    }


@router.get("/recipe", summary="Recipe Mock Data")
async def get_recipe(
    lot_id: str = Query(..., description="Lot ID"),
    tool_id: str = Query(..., description="Tool ID"),
    operation_number: str = Query(..., description="Operation number"),
):
    """Return recipe parameters with dynamic 12-hour-ago last-modified time."""
    # Dynamic: 12 hours ago from NOW (as spec requires)
    last_modified = datetime.now(tz=timezone.utc) - timedelta(hours=12)

    seed = hash(lot_id + tool_id + operation_number) % 1000

    return {
        "lot_id": lot_id,
        "tool_id": tool_id,
        "operation_number": operation_number,
        "recipe_name": f"RCP_{operation_number}_{seed % 10:03d}",
        "parameters": {
            "pressure": round(10.0 + (seed % 50) / 10, 2),
            "rf_power": 500 + (seed % 200),
            "bias_power": 100 + (seed % 100),
            "gas_he": round(20.0 + (seed % 30) / 10, 1),
            "gas_cf4": round(50.0 + (seed % 50) / 10, 1),
            "temperature": 20 + (seed % 10),
            "time": 60 + (seed % 60),
        },
        "last_modified_at": last_modified.isoformat(),
        "modified_by": f"pe_user_{seed % 5 + 1:02d}",
        "version": seed % 20 + 1,
        "is_locked": seed % 3 == 0,
    }


@router.get("/ec", summary="Equipment Constants Mock Data")
async def get_ec(
    tool_id: str = Query(..., description="Tool ID"),
):
    """Return equipment hardware parameter baselines."""
    seed = hash(tool_id) % 1000

    return {
        "tool_id": tool_id,
        "tool_type": "Etch",
        "chamber": f"CH{seed % 4 + 1}",
        "hardware_constants": {
            "rf_matching_cap_c1": round(45.0 + (seed % 20) / 10, 2),
            "rf_matching_cap_c2": round(55.0 + (seed % 20) / 10, 2),
            "throttle_valve_position": round(65.0 + (seed % 30) / 10, 1),
            "turbopump_speed": 60000 + (seed % 5000),
            "bias_frequency_hz": 13560000,
            "source_frequency_hz": 13560000,
        },
        "baseline_date": (datetime.now(tz=timezone.utc) - timedelta(days=30 + seed % 60)).isoformat(),
        "pm_status": "normal" if seed % 4 != 0 else "pm_due",
        "maintenance_cycle_days": 90 + (seed % 30),
    }


@router.get("/spc", summary="SPC Chart Mock Data")
async def get_spc(
    chart_name: Optional[str] = Query(default=None, description="Filter by chart name (optional, e.g. CD)"),
    lot_id: Optional[str] = Query(default=None, description="Filter by lot ID (optional). Falls back to all records if not found."),
    tool_id: Optional[str] = Query(default=None, description="Filter by tool ID (optional, e.g. TETCH01)"),
):
    """Return SPC chart data for Etch CD measurement.

    100 records total — 10 tools (TETCH01-10) × 10 lots each.
    TETCH01 lots 1-4 are intentionally OOC (above UCL 46.5) to simulate SPC_OOC_Etch_CD events.
    lot_id / tool_id filters: if provided but no match found, returns all records (mock fallback).
    """
    base_time = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    UCL = 46.5
    LCL = 43.5

    # TETCH01: first 4 lots OOC (above UCL), remaining normal
    _tetch01_values = [47.2, 46.9, 47.5, 46.6, 44.8, 45.1, 44.6, 45.3, 44.9, 45.2]

    # TETCH02-10: all within control limits (~44.6–45.3 nm)
    _normal_values = [
        [45.0, 44.8, 45.2, 44.7, 45.1, 44.9, 45.3, 44.6, 45.0, 44.8],  # TETCH02
        [44.9, 45.1, 44.8, 45.2, 44.7, 45.0, 44.6, 45.3, 44.9, 45.1],  # TETCH03
        [45.2, 44.9, 45.0, 44.8, 45.1, 44.7, 45.3, 44.6, 45.0, 44.9],  # TETCH04
        [44.7, 45.1, 44.9, 45.2, 44.8, 45.0, 44.7, 45.2, 44.9, 45.0],  # TETCH05
        [45.1, 44.8, 45.3, 44.7, 45.0, 44.9, 45.2, 44.8, 45.1, 44.7],  # TETCH06
        [44.8, 45.0, 44.9, 45.2, 44.7, 45.1, 44.8, 45.3, 44.9, 45.0],  # TETCH07
        [45.0, 44.9, 45.1, 44.8, 45.2, 44.7, 45.0, 44.9, 45.1, 44.8],  # TETCH08
        [44.9, 45.1, 44.8, 45.0, 44.7, 45.2, 44.9, 45.1, 44.8, 45.0],  # TETCH09
        [45.1, 44.8, 45.0, 44.9, 45.2, 44.7, 45.1, 44.8, 45.0, 44.9],  # TETCH10
    ]

    records = []
    idx = 0
    for t_idx in range(10):
        tool = f"TETCH{t_idx + 1:02d}"
        recipe = f"ETH_RCP_{t_idx + 1:02d}"
        values = _tetch01_values if t_idx == 0 else _normal_values[t_idx - 1]
        for j in range(10):
            lot_num = t_idx * 10 + j + 1
            record_lot_id = f"L2603{lot_num:03d}"  # use a different name to avoid shadowing the query param
            dt = (base_time - timedelta(minutes=idx * 5)).isoformat()
            records.append(
                {
                    "datetime": dt,
                    "value": values[j],
                    "UCL": UCL,
                    "LCL": LCL,
                    "tool": tool,
                    "lotID": record_lot_id,
                    "recipe": recipe,
                    "DCItem": "CD",
                    "ChartName": "CD",
                }
            )
            idx += 1

    if chart_name:
        records = [r for r in records if r["ChartName"] == chart_name]

    if tool_id:
        filtered = [r for r in records if r["tool"].lower() == tool_id.lower()]
        if filtered:
            records = filtered

    if lot_id:
        filtered = [r for r in records if r["lotID"].lower() == lot_id.lower()]
        if filtered:
            records = filtered
        else:
            # lot_id not in fixed mock data (e.g. user typed "AAAAA").
            # Generate 10 deterministic SPC records WITH that exact lotID so the
            # processing script's lotID filter always finds data — same hash-seed
            # pattern as /mock/apc.
            import random
            rng = random.Random(abs(hash(lot_id)) % (2 ** 32))
            gen = []
            for i in range(10):
                tool_num = (i % 10) + 1
                tool     = f"TETCH{tool_num:02d}"
                recipe   = f"ETH_RCP_{tool_num:02d}"
                # 20 % chance OOC (> UCL 46.5), otherwise in-control
                if rng.random() < 0.2:
                    value = round(rng.uniform(46.6, 47.5), 1)
                else:
                    value = round(rng.uniform(44.2, 46.4), 1)
                dt = (base_time - timedelta(minutes=i * 15)).isoformat()
                gen.append({
                    "datetime": dt,
                    "value":    value,
                    "UCL":      UCL,
                    "LCL":      LCL,
                    "tool":     tool,
                    "lotID":    lot_id,   # ← exact queried lot_id
                    "recipe":   recipe,
                    "DCItem":   "CD",
                    "ChartName": "CD",
                })
            records = gen

    return records


@router.get("/apc_tuning", summary="APC Tuning Value Mock Data")
async def get_apc_tuning(
    apc_name: Optional[str] = Query(default=None, description="Filter by APC controller name (optional, e.g. TETCH01_CD_Control)"),
):
    """Return APC tuning values (etchTime) per lot for all 10 Etch CD controllers.

    100 records total — 10 controllers (TETCH01-10_CD_Control) × 10 lots each.
    ReportTime is dynamic: base = now - 1h, each record -5 min (most recent first).
    TETCH01 lots 1-4 have intentionally low etchTime (5~6 sec) correlating with
    the SPC_Chart_Data OOC events on those same lots (CD too high → etch time too short).
    """
    # Dynamic base: 1 hour before current time (mirrors real APC reporting cadence)
    base_report = datetime.now(tz=timezone.utc) - timedelta(hours=1)

    # TETCH01: first 4 lots have low etchTime (→ under-etching → high CD → OOC)
    _tetch01_values = [5.3, 5.8, 5.1, 6.2, 12.3, 11.8, 13.1, 12.7, 11.5, 13.4]

    # TETCH02-10: all normal etchTime (10~15 sec)
    _normal_values = [
        [12.1, 11.7, 13.2, 12.4, 11.9, 13.0, 12.6, 11.4, 12.8, 13.3],  # TETCH02
        [11.6, 12.9, 13.1, 11.8, 12.3, 11.5, 13.4, 12.0, 11.7, 12.5],  # TETCH03
        [13.2, 12.0, 11.9, 13.4, 12.6, 11.6, 12.8, 13.0, 11.4, 12.2],  # TETCH04
        [11.8, 13.3, 12.5, 11.7, 13.0, 12.4, 11.5, 13.1, 12.7, 11.9],  # TETCH05
        [12.4, 11.6, 13.3, 12.1, 11.8, 13.2, 12.3, 11.5, 13.0, 12.6],  # TETCH06
        [11.9, 13.1, 12.2, 11.7, 13.4, 12.5, 11.6, 12.9, 13.2, 11.8],  # TETCH07
        [13.0, 11.8, 12.7, 13.3, 11.5, 12.4, 13.1, 12.0, 11.7, 12.8],  # TETCH08
        [12.3, 13.4, 11.6, 12.9, 12.1, 11.8, 13.2, 12.5, 11.7, 13.0],  # TETCH09
        [11.7, 12.6, 13.3, 11.9, 12.2, 13.0, 11.5, 12.8, 13.1, 11.6],  # TETCH10
    ]

    records = []
    idx = 0
    for t_idx in range(10):
        controller = f"TETCH{t_idx + 1:02d}_CD_Control"
        values = _tetch01_values if t_idx == 0 else _normal_values[t_idx - 1]
        for j in range(10):
            lot_num = t_idx * 10 + j + 1
            lot_id = f"L2603{lot_num:03d}"
            report_time = (base_report - timedelta(minutes=idx * 5)).isoformat()
            records.append(
                {
                    "APCName":    controller,
                    "ReportTime": report_time,
                    "DCName":     "etchTime",
                    "DCValue":    values[j],
                    "LotID":      lot_id,
                }
            )
            idx += 1

    if apc_name:
        records = [r for r in records if r["APCName"] == apc_name]

    return records
