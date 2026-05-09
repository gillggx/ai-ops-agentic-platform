"""SPC Service – Phase 12 expansion: 12 control charts (was 5), each tracking
a specific DC sensor with mean ± k·σ control limits. The k factor depends on
lot_type (production = 1.5σ ≈ 86.6% confidence; monitor = 2.0σ ≈ 95.4%) so
monitor lots OOC less often than production at the same drift level.

OOC status is derived from ACTUAL limit violations, not randomness.

Charts (sensor → spec):
  xbar_chart        chamber_pressure         (mTorr)
  r_chart           bias_voltage_v           (V)
  s_chart           esc_zone1_temp           (°C)
  p_chart           cf4_flow_sccm            (sccm)
  c_chart           rf_forward_power         (W)
  imr_pressure      foreline_pressure        (mTorr)  individual measurement
  cusum_temp        chuck_temp_c             (°C)     cumulative shift
  ewma_bias         bias_power_lf_w          (W)      exp-weighted moving avg
  cpk_etch          rf_2nd_harmonic_w        (W)      capability index proxy
  oes_endpoint      oes_endpoint_signal      (au)     end-point composite
  rga_h2o_chart     rga_h2o_partial          (Torr)   contamination signal
  match_tune_chart  match_tune_position      (%)      auto-tune drift
"""
from app.database import get_db
from config import SPC_SD_PRODUCTION, SPC_SD_MONITOR

# ── Control chart specs ───────────────────────────────────────
# Each chart: {sensor, mean, sd}. UCL/LCL = mean ± k·sd, k from lot_type.
# Mean & SD are picked so production (k=1.5) limits roughly match the
# legacy hardcoded values, keeping baseline OOC rate stable.
_CHART_SPECS: dict[str, dict] = {
    "xbar_chart":       {"sensor": "chamber_pressure",      "mean": 15.00,    "sd": 1.667},
    "r_chart":          {"sensor": "bias_voltage_v",         "mean": 850.00,   "sd": 20.0},
    "s_chart":          {"sensor": "esc_zone1_temp",         "mean": 60.00,    "sd": 1.667},
    "p_chart":          {"sensor": "cf4_flow_sccm",          "mean": 50.00,    "sd": 4.0},
    "c_chart":          {"sensor": "rf_forward_power",       "mean": 1500.00,  "sd": 46.67},
    # Phase 12 new charts ----------------------------------------------------
    # SD chosen so UCL/LCL (mean ± 1.5σ for production) sits just outside
    # the DC physical range from dc_service._SENSOR_RANGES. Original Phase 12
    # SDs were too tight (e.g. cpk_etch UCL=15.5 with DC range 5-18 → 50%
    # natural OOC), inflating SPC OOC rate to ~100% on every event. These
    # widened values restore natural OOC ≈ baseline; intentional drift /
    # excursion injection in dc_service still trips the original 5 charts.
    "imr_pressure":     {"sensor": "foreline_pressure",      "mean":  1.30,    "sd":  0.40},
    "cusum_temp":       {"sensor": "chuck_temp_c",           "mean": 20.00,    "sd":  0.80},
    "ewma_bias":        {"sensor": "bias_power_lf_w",        "mean": 400.00,   "sd": 55.0},
    "cpk_etch":         {"sensor": "rf_2nd_harmonic_w",      "mean":  11.5,    "sd":  5.5},
    "oes_endpoint":     {"sensor": "oes_endpoint_signal",    "mean":  0.50,    "sd":  0.25},
    "rga_h2o_chart":    {"sensor": "rga_h2o_partial",        "mean":  3e-9,    "sd":  1.6e-9},
    "match_tune_chart": {"sensor": "match_tune_position",    "mean": 50.00,    "sd":  8.0},
}


def evaluate(dc_params: dict, lot_type: str = "production") -> tuple[str, dict]:
    """Evaluate 12 control charts from DC readings.

    Phase 12: lot_type widens / tightens the control limits.
      - production: ±1.5σ (default, legacy behaviour)
      - monitor:    ±2.0σ (looser; monitor lots are check vehicles, not
                           expected to OOC frequently)
      - other:      ±1.5σ (engineering / qual)
    """
    k = SPC_SD_MONITOR if lot_type == "monitor" else SPC_SD_PRODUCTION
    charts: dict[str, dict] = {}
    any_ooc = False

    for chart_id, spec in _CHART_SPECS.items():
        value = dc_params.get(spec["sensor"], 0.0)
        ucl = spec["mean"] + k * spec["sd"]
        lcl = spec["mean"] - k * spec["sd"]
        is_ooc = not (lcl <= value <= ucl)
        if is_ooc:
            any_ooc = True
        # Phase 12: 6-decimal round nukes sub-µ scale charts (rga_h2o ~1e-9
        # rounds to 0). 12 decimals keeps small-scale sensors visible while
        # still trimming float noise on regular engineering scales.
        charts[chart_id] = {
            "value":  round(value, 12),
            "ucl":    round(ucl, 12),
            "lcl":    round(lcl, 12),
            "mean":   round(spec["mean"], 12),
            "sd":     round(spec["sd"], 12),
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
        "chamberID":        context.get("chamberID"),    # Phase 12
        "lot_type":         context.get("lot_type", "production"),
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
