"""SPC Service – 5 control charts, each tracking a SPECIFIC sensor with physical
control limits.  OOC status is derived from ACTUAL limit violations, not randomness.

Charts:
  xbar_chart  chamber_pressure   mTorr   LCL=12.5   UCL=17.5
  r_chart     bias_voltage_v     V       LCL=820    UCL=880
  s_chart     esc_zone1_temp     °C      LCL=57.5   UCL=62.5
  p_chart     cf4_flow_sccm      sccm    LCL=44     UCL=56
  c_chart     rf_forward_power   W       LCL=1430   UCL=1570
"""
from app.database import get_db

# ── Control chart specs ───────────────────────────────────────
_CHART_SPECS: dict[str, dict] = {
    "xbar_chart": {"sensor": "chamber_pressure",  "ucl": 17.5,   "lcl": 12.5},
    "r_chart":    {"sensor": "bias_voltage_v",     "ucl": 880.0,  "lcl": 820.0},
    "s_chart":    {"sensor": "esc_zone1_temp",     "ucl": 62.5,   "lcl": 57.5},
    "p_chart":    {"sensor": "cf4_flow_sccm",      "ucl": 56.0,   "lcl": 44.0},
    "c_chart":    {"sensor": "rf_forward_power",   "ucl": 1570.0, "lcl": 1430.0},
}


def evaluate(dc_params: dict) -> tuple[str, dict]:
    """Evaluate 5 control charts from DC readings.

    Returns (spc_status, charts_dict).
    spc_status: "OOC" if ANY chart breaches, else "PASS".
    """
    charts: dict[str, dict] = {}
    any_ooc = False

    for chart_id, spec in _CHART_SPECS.items():
        value = dc_params.get(spec["sensor"], 0.0)
        is_ooc = not (spec["lcl"] <= value <= spec["ucl"])
        if is_ooc:
            any_ooc = True
        charts[chart_id] = {
            "value": round(value, 4),
            "ucl":   spec["ucl"],
            "lcl":   spec["lcl"],
            "is_ooc": is_ooc,
        }

    status = "OOC" if any_ooc else "PASS"
    return status, charts


async def upload_snapshot(spc_status: str, charts: dict, context: dict) -> str:
    """Write SPC snapshot with unified eventTime. Returns inserted _id."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "SPC",
        "objectID":         f"SPC-{context['step']}",
        "charts":           charts,
        "spc_status":       spc_status,
        "last_updated_time": context["eventTime"],
        "updated_by":       "spc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
