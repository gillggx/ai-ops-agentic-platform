"""SPC Service – 5 control charts, each tracking a SPECIFIC sensor with physical
control limits.  OOC status is derived from ACTUAL limit violations, not randomness.

Charts:
  xbar_chart  Chamber Press (sensor_01)  mTorr   LCL=12.5  UCL=17.5
  r_chart     Bias Voltage  (sensor_19)  V       LCL=820   UCL=880
  s_chart     ESC Zone1 Temp(sensor_07)  °C      LCL=57.5  UCL=62.5
  p_chart     CF4 Flow      (sensor_23)  sccm    LCL=44    UCL=56
  c_chart     Source Pwr HF (sensor_15)  W       LCL=1430  UCL=1570
"""
from app.database import get_db

# ── Control chart specs ───────────────────────────────────────
_CHART_SPECS: dict[str, dict] = {
    "xbar_chart": {"sensor": "sensor_01", "ucl": 17.5,   "lcl": 12.5},
    "r_chart":    {"sensor": "sensor_19", "ucl": 880.0,  "lcl": 820.0},
    "s_chart":    {"sensor": "sensor_07", "ucl": 62.5,   "lcl": 57.5},
    "p_chart":    {"sensor": "sensor_23", "ucl": 56.0,   "lcl": 44.0},
    "c_chart":    {"sensor": "sensor_15", "ucl": 1570.0, "lcl": 1430.0},
}


def evaluate(dc_params: dict) -> tuple[dict, str]:
    """Evaluate 5 control charts from DC readings; OOC if ANY chart breaches limits."""
    charts: dict[str, dict] = {}
    any_ooc = False

    for chart_id, spec in _CHART_SPECS.items():
        value = dc_params.get(spec["sensor"], 0.0)
        in_ctrl = spec["lcl"] <= value <= spec["ucl"]
        if not in_ctrl:
            any_ooc = True
        charts[chart_id] = {
            "value": round(value, 4),
            "ucl":   spec["ucl"],
            "lcl":   spec["lcl"],
        }

    status = "OOC" if any_ooc else "PASS"
    return charts, status


async def evaluate_and_upload(dc_params: dict, context: dict) -> tuple[str, str]:
    """Evaluate SPC, store snapshot, return (snapshot_id, status)."""
    db = get_db()
    charts, status = evaluate(dc_params)

    ts = context["eventTime"].strftime("%Y%m%d%H%M%S%f")
    snapshot = {
        "eventTime":         context["eventTime"],
        "lotID":             context["lotID"],
        "toolID":            context["toolID"],
        "step":              context["step"],
        "objectName":        "SPC",
        "objectID":          f"SPC-{context['lotID']}-{context['step']}-{ts}",
        "charts":            charts,
        "spc_status":        status,
        "last_updated_time": context["eventTime"],
        "updated_by":        "spc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id), status
