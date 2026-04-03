"""SPC Service – 5 control charts, each tracking a SPECIFIC sensor with physical
control limits.  OOC status is derived from ACTUAL limit violations, not randomness.

Charts:
  xbar_chart  chamber_pressure   mTorr   LCL=12.5   UCL=17.5
  r_chart     bias_voltage_v     V       LCL=820    UCL=880
  s_chart     esc_zone1_temp     °C      LCL=57.5   UCL=62.5
  p_chart     cf4_flow_sccm      sccm    LCL=44     UCL=56
  c_chart     rf_forward_power   W       LCL=1430   UCL=1570
"""
import asyncio

from app.database import get_db
from app.services.ooc_event_publisher import OOCDetail, OOCEventPayload, publish_ooc_event

# ── Control chart specs ───────────────────────────────────────
_CHART_SPECS: dict[str, dict] = {
    "xbar_chart": {"sensor": "chamber_pressure",  "ucl": 17.5,   "lcl": 12.5},
    "r_chart":    {"sensor": "bias_voltage_v",     "ucl": 880.0,  "lcl": 820.0},
    "s_chart":    {"sensor": "esc_zone1_temp",     "ucl": 62.5,   "lcl": 57.5},
    "p_chart":    {"sensor": "cf4_flow_sccm",      "ucl": 56.0,   "lcl": 44.0},
    "c_chart":    {"sensor": "rf_forward_power",   "ucl": 1570.0, "lcl": 1430.0},
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
        "status":            context.get("status", "ProcessEnd"),
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

    # ── Publish OOC event to NATS if any chart is out-of-control ─────────────
    if status == "OOC":
        # Find the first breached chart to populate ooc_details
        first_breach = next(
            (
                (chart_id, spec, charts[chart_id])
                for chart_id, spec in _CHART_SPECS.items()
                if not (spec["lcl"] <= dc_params.get(spec["sensor"], 0.0) <= spec["ucl"])
            ),
            None,
        )
        if first_breach:
            chart_id, spec, chart_data = first_breach
            ooc_payload = OOCEventPayload(
                equipment_id=context.get("toolID", "UNKNOWN"),
                lot_id=context.get("lotID", "UNKNOWN"),
                step_id=context.get("step", "UNKNOWN"),
                parameter=spec["sensor"],
                ooc_details=OOCDetail(
                    rule="Limit Violation",
                    value=round(dc_params.get(spec["sensor"], 0.0), 4),
                    ucl=spec["ucl"],
                    lcl=spec["lcl"],
                ),
                severity="warning",
            )
            # Fire-and-forget: don't block the simulation pipeline
            asyncio.create_task(publish_ooc_event(ooc_payload))

    return str(result.inserted_id), status
