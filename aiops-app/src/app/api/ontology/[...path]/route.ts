/**
 * Ontology Adapter Layer
 *
 * Responsibilities:
 *  1. Proxy to OntologySimulator (EQP-xx, MongoDB, raw sensor/param keys)
 *  2. Normalize schema: equipment_id, status(lowercase), human-readable names
 *  3. Translate internal keys → labelled, grouped parameter objects
 *     so downstream consumers (UI, AI agent) never see raw param_xx / sensor_xx keys
 */
import { NextRequest, NextResponse } from "next/server";

const ONTOLOGY_BASE = process.env.ONTOLOGY_BASE_URL ?? "http://localhost:8012";

// ---------------------------------------------------------------------------
// Equipment mappings
// ---------------------------------------------------------------------------

const STATUS_MAP: Record<string, string> = {
  Idle:        "idle",
  Busy:        "running",
  Processing:  "running",
  Hold:        "alarm",
  Maintenance: "maintenance",
  Down:        "down",
  Error:       "alarm",
};

const TOOL_NAMES: Record<string, string> = {
  "EQP-01": "Etch Tool 01",
  "EQP-02": "CVD Tool 01",
  "EQP-03": "CMP Tool 01",
  "EQP-04": "Implant Tool 01",
  "EQP-05": "Litho Tool 01",
  "EQP-06": "Diffusion Tool 01",
  "EQP-07": "Metrology Tool 01",
  "EQP-08": "Clean Tool 01",
  "EQP-09": "Oxidation Tool 01",
  "EQP-10": "Deposition Tool 01",
};

// Map UI display name → raw DC sensor key (for timeseries endpoint)
const PARAM_KEY_MAP: Record<string, string> = {
  Temperature:       "sensor_07",   // ESC Zone1 Temp
  Pressure:          "sensor_01",   // Chamber Press
  "RF Power":        "sensor_15",   // Source Power HF
  "Bias Voltage":    "sensor_19",
  "Chamber Press":   "sensor_01",
  "Foreline Press":  "sensor_02",
  "ESC Zone1 Temp":  "sensor_07",
  "ESC Zone2 Temp":  "sensor_08",
  "Chuck Temp":      "sensor_10",
  "Source Power HF": "sensor_15",
  "Bias Power LF":   "sensor_17",
  "CF4 Flow":        "sensor_23",
  "O2 Flow":         "sensor_24",
  "Total Flow":      "sensor_30",
};

// ---------------------------------------------------------------------------
// Parameter label tables  (internal key → { name, unit, group })
// ---------------------------------------------------------------------------

interface ParamLabel { name: string; unit: string; group: string; }

// DC: sensor_01..sensor_30
const DC_LABELS: Record<string, ParamLabel> = {
  sensor_01: { name: "Chamber Press",  unit: "mTorr", group: "Vacuum"  },
  sensor_02: { name: "Foreline Press", unit: "mTorr", group: "Vacuum"  },
  sensor_03: { name: "Load Lock Press",unit: "mTorr", group: "Vacuum"  },
  sensor_04: { name: "Transfer Press", unit: "mTorr", group: "Vacuum"  },
  sensor_05: { name: "Throttle Pos",   unit: "%",     group: "Vacuum"  },
  sensor_06: { name: "Gate Valve Pos", unit: "%",     group: "Vacuum"  },
  sensor_07: { name: "ESC Zone1 Temp", unit: "°C",    group: "Thermal" },
  sensor_08: { name: "ESC Zone2 Temp", unit: "°C",    group: "Thermal" },
  sensor_09: { name: "ESC Zone3 Temp", unit: "°C",    group: "Thermal" },
  sensor_10: { name: "Chuck Temp",     unit: "°C",    group: "Thermal" },
  sensor_11: { name: "Wall Temp",      unit: "°C",    group: "Thermal" },
  sensor_12: { name: "Ceiling Temp",   unit: "°C",    group: "Thermal" },
  sensor_13: { name: "Gas Inlet Temp", unit: "°C",    group: "Thermal" },
  sensor_14: { name: "Exhaust Temp",   unit: "°C",    group: "Thermal" },
  sensor_15: { name: "Source Power HF",unit: "W",     group: "RF Power"},
  sensor_16: { name: "Source Refl HF", unit: "W",     group: "RF Power"},
  sensor_17: { name: "Bias Power LF",  unit: "W",     group: "RF Power"},
  sensor_18: { name: "Bias Refl LF",   unit: "W",     group: "RF Power"},
  sensor_19: { name: "Bias Voltage",   unit: "V",     group: "RF Power"},
  sensor_20: { name: "Bias Current",   unit: "A",     group: "RF Power"},
  sensor_21: { name: "Source Freq",    unit: "MHz",   group: "RF Power"},
  sensor_22: { name: "Match Cap C1",   unit: "pF",    group: "RF Power"},
  sensor_23: { name: "CF4 Flow",       unit: "sccm",  group: "Gas Flow"},
  sensor_24: { name: "O2 Flow",        unit: "sccm",  group: "Gas Flow"},
  sensor_25: { name: "Ar Flow",        unit: "sccm",  group: "Gas Flow"},
  sensor_26: { name: "N2 Flow",        unit: "sccm",  group: "Gas Flow"},
  sensor_27: { name: "He Flow",        unit: "sccm",  group: "Gas Flow"},
  sensor_28: { name: "CHF3 Flow",      unit: "sccm",  group: "Gas Flow"},
  sensor_29: { name: "C4F8 Flow",      unit: "sccm",  group: "Gas Flow"},
  sensor_30: { name: "Total Flow",     unit: "sccm",  group: "Gas Flow"},
};

// APC: param_01..param_20
const APC_LABELS: Record<string, ParamLabel> = {
  param_01: { name: "R2R Bias",         unit: "nm",     group: "Run-to-Run"      },
  param_02: { name: "R2R Gain",         unit: "—",      group: "Run-to-Run"      },
  param_03: { name: "R2R Offset",       unit: "nm",     group: "Run-to-Run"      },
  param_04: { name: "Model Intercept",  unit: "—",      group: "Run-to-Run"      },
  param_05: { name: "Target CD",        unit: "nm",     group: "Process Setpoints"},
  param_06: { name: "Target EPD",       unit: "s",      group: "Process Setpoints"},
  param_07: { name: "Etch Rate",        unit: "nm/min", group: "Process Setpoints"},
  param_08: { name: "Uniformity",       unit: "%",      group: "Process Setpoints"},
  param_09: { name: "FF Correction",    unit: "—",      group: "Feed-Forward"    },
  param_10: { name: "FF Weight",        unit: "—",      group: "Feed-Forward"    },
  param_11: { name: "FF Alpha",         unit: "—",      group: "Feed-Forward"    },
  param_12: { name: "Lot Weight",       unit: "—",      group: "Feed-Forward"    },
  param_13: { name: "FB Correction",    unit: "—",      group: "Feedback & Model"},
  param_14: { name: "FB Alpha",         unit: "—",      group: "Feedback & Model"},
  param_15: { name: "Model R²",         unit: "—",      group: "Feedback & Model"},
  param_16: { name: "Stability Index",  unit: "—",      group: "Feedback & Model"},
  param_17: { name: "Prediction Error", unit: "nm",     group: "Feedback & Model"},
  param_18: { name: "Convergence Idx",  unit: "—",      group: "Feedback & Model"},
  param_19: { name: "Reg λ",            unit: "—",      group: "Feedback & Model"},
  param_20: { name: "Response Factor",  unit: "—",      group: "Feedback & Model"},
};

// RECIPE: param_01..param_20
const RECIPE_LABELS: Record<string, ParamLabel> = {
  param_01: { name: "Etch Time",      unit: "s",      group: "Etch"    },
  param_02: { name: "Etch Depth",     unit: "nm",     group: "Etch"    },
  param_03: { name: "Etch Rate",      unit: "nm/s",   group: "Etch"    },
  param_04: { name: "CD Bias",        unit: "nm",     group: "Etch"    },
  param_05: { name: "Over-Etch",      unit: "%",      group: "Etch"    },
  param_06: { name: "Process Press",  unit: "mTorr",  group: "Chamber" },
  param_07: { name: "Base Press",     unit: "mTorr",  group: "Chamber" },
  param_08: { name: "Chamber Temp",   unit: "°C",     group: "Chamber" },
  param_09: { name: "Wall Temp",      unit: "°C",     group: "Chamber" },
  param_10: { name: "CF4 Setpoint",   unit: "sccm",   group: "Gas"     },
  param_11: { name: "O2 Setpoint",    unit: "sccm",   group: "Gas"     },
  param_12: { name: "Ar Setpoint",    unit: "sccm",   group: "Gas"     },
  param_13: { name: "He Setpoint",    unit: "sccm",   group: "Gas"     },
  param_14: { name: "Source Power",   unit: "W",      group: "RF"      },
  param_15: { name: "Bias Power",     unit: "W",      group: "RF"      },
  param_16: { name: "Source Freq",    unit: "MHz",    group: "RF"      },
  param_17: { name: "Bias Freq",      unit: "kHz",    group: "RF"      },
  param_18: { name: "EPD Threshold",  unit: "AU",     group: "Endpoint"},
  param_19: { name: "Min Etch Time",  unit: "s",      group: "Endpoint"},
  param_20: { name: "Max Etch Time",  unit: "s",      group: "Endpoint"},
};

// SPC chart labels
const SPC_CHART_LABELS: Record<string, { name: string; sensor: string }> = {
  xbar_chart: { name: "Chamber Press",  sensor: "sensor_01" },
  r_chart:    { name: "Bias Voltage",   sensor: "sensor_19" },
  s_chart:    { name: "ESC Zone1 Temp", sensor: "sensor_07" },
  p_chart:    { name: "CF4 Flow",       sensor: "sensor_23" },
  c_chart:    { name: "Source Power HF",sensor: "sensor_15" },
};

// EC component health labels
const EC_HEALTH_LABELS: Record<string, { name: string }> = {
  rf_match: { name: "RF Match" },
  esc:      { name: "ESC" },
  gas_box:  { name: "Gas Box" },
  exhaust:  { name: "Exhaust" },
};

// FDC fault code descriptions (Chinese)
const FDC_FAULT_DESCRIPTIONS: Record<string, string> = {
  PRESSURE_SPIKE:   "腔體壓力異常飆升",
  TEMP_EXCURSION:   "ESC 溫度偏移超限",
  RF_POWER_DRIFT:   "RF 功率源漂移",
  BIAS_ANOMALY:     "偏壓電壓異常",
  GAS_FLOW_ANOMALY: "製程氣體流量異常",
  PARAMETER_DRIFT:  "製程參數緩慢漂移",
  UNKNOWN_FAULT:    "未知故障",
  NORMAL:           "製程正常",
};

// ---------------------------------------------------------------------------
// Translation helpers
// ---------------------------------------------------------------------------

function addLabels(
  params: Record<string, unknown>,
  labelMap: Record<string, ParamLabel>,
): { parameters: Record<string, unknown>; labels: Record<string, ParamLabel> } {
  const labels: Record<string, ParamLabel> = {};
  for (const key of Object.keys(params)) {
    if (labelMap[key]) labels[key] = labelMap[key];
  }
  return { parameters: params, labels };
}

function enrichSpc(spc: Record<string, unknown>) {
  return {
    ...spc,
    chart_labels: SPC_CHART_LABELS,
  };
}

// ---------------------------------------------------------------------------
// Normalizers
// ---------------------------------------------------------------------------

function normalizeTool(t: Record<string, unknown>) {
  const toolId = t.tool_id as string;
  return {
    equipment_id:  toolId,
    name:          TOOL_NAMES[toolId] ?? toolId,
    status:        STATUS_MAP[t.status as string] ?? (t.status as string ?? "").toLowerCase(),
    chamber_count: 1,
    last_updated:  new Date().toISOString(),
  };
}

function normalizeEvent(e: Record<string, unknown>, idx: number) {
  const spcStatus = (e.spc_status as string) ?? "";
  const severity  = spcStatus === "OOC"  ? "warning"
                  : spcStatus === "FAIL" ? "critical"
                  : "info";
  const status = (e.status as string) ?? "";
  return {
    event_id:     `${e.toolID}-${e.step}-${idx}`,
    equipment_id: e.toolID as string,
    event_type:   status,
    severity,
    description:  `${status} | ${e.lotID ?? ""} @ ${e.step ?? ""}`,
    timestamp:    e.eventTime as string,
    resolved_at:  null,
    metadata:     { lotID: e.lotID, step: e.step, spc_status: spcStatus, recipeID: e.recipeID, apcID: e.apcID },
  };
}

function buildTimeseries(
  equipmentId: string,
  parameter: string,
  snapshots: Record<string, unknown>[],
) {
  const paramKey = PARAM_KEY_MAP[parameter] ?? parameter;

  const raw: { ts: string; value: number }[] = [];
  for (const snap of snapshots) {
    const params = snap.parameters as Record<string, unknown> | undefined;
    if (!params) continue;
    let v = params[paramKey];
    if (v == null) v = Object.values(params).find((x) => typeof x === "number");
    if (typeof v !== "number") continue;
    raw.push({ ts: snap.eventTime as string, value: v });
  }

  if (raw.length === 0) {
    return { equipment_id: equipmentId, parameter, ucl: 0, lcl: 0, mean: 0, data: [] };
  }

  const values = raw.map((r) => r.value);
  const mean   = values.reduce((a, b) => a + b, 0) / values.length;
  const std    = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length);
  const ucl    = mean + 3 * std;
  const lcl    = mean - 3 * std;

  const data = raw.map((r) => ({
    timestamp: r.ts,
    value:     Math.round(r.value * 1000) / 1000,
    is_ooc:    r.value > ucl || r.value < lcl,
  }));

  return {
    equipment_id: equipmentId,
    parameter,
    ucl:  Math.round(ucl  * 1000) / 1000,
    lcl:  Math.round(lcl  * 1000) / 1000,
    mean: Math.round(mean * 1000) / 1000,
    data,
  };
}

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

async function getEquipmentList() {
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/tools`, { cache: "no-store" });
  if (!res.ok) throw new Error(`tools ${res.status}`);
  const tools = await res.json() as Record<string, unknown>[];
  const items = tools.map(normalizeTool);
  return NextResponse.json({ total: items.length, items });
}

async function getEquipmentOne(id: string) {
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/tools`, { cache: "no-store" });
  if (!res.ok) throw new Error(`tools ${res.status}`);
  const tools = await res.json() as Record<string, unknown>[];
  const tool  = tools.find((t) => (t.tool_id as string) === id);
  if (!tool) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json(normalizeTool(tool));
}

async function getDcTimeseries(id: string, searchParams: URLSearchParams) {
  const parameter = searchParams.get("parameter") ?? "Temperature";
  const url = `${ONTOLOGY_BASE}/api/v1/analytics/history?targetID=${id}&objectName=DC&limit=100`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`analytics/history ${res.status}`);
  const snapshots = await res.json() as Record<string, unknown>[];
  return NextResponse.json(buildTimeseries(id, parameter, snapshots));
}

async function getEvents(searchParams: URLSearchParams) {
  const equipmentId = searchParams.get("equipment_id") ?? "";
  const lotId       = searchParams.get("lot_id")       ?? "";
  const recipeId    = searchParams.get("recipe_id")    ?? "";
  const apcId       = searchParams.get("apc_id")       ?? "";
  const limit       = searchParams.get("limit")        ?? "50";

  // RECIPE / APC events: fetch all recent, filter in adapter
  if (recipeId || apcId) {
    const res = await fetch(`${ONTOLOGY_BASE}/api/v1/events?limit=500`, { cache: "no-store" });
    if (!res.ok) throw new Error(`events ${res.status}`);
    const all = await res.json() as Record<string, unknown>[];
    const filtered = all.filter((e) =>
      recipeId ? e.recipeID === recipeId : e.apcID === apcId
    ).slice(0, Number(limit));
    const items = filtered.map((e, i) => normalizeEvent(e, i));
    return NextResponse.json({ recipe_id: recipeId, apc_id: apcId, total: items.length, items });
  }

  const qs = lotId ? `lotID=${lotId}` : `toolID=${equipmentId}`;
  const url = `${ONTOLOGY_BASE}/api/v1/events?${qs}&limit=${limit}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`events ${res.status}`);
  const events = await res.json() as Record<string, unknown>[];
  const items  = events.map((e, i) => normalizeEvent(e, i));
  return NextResponse.json({ equipment_id: equipmentId, lot_id: lotId, total: items.length, items });
}

async function getLots() {
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/lots`, { cache: "no-store" });
  if (!res.ok) throw new Error(`lots ${res.status}`);
  return NextResponse.json(await res.json());
}

/** List objects by type for sidebar browsing */
async function getObjectList(type: string) {
  // DC / SPC → lot-bound → proxy lots list
  if (type === "DC" || type === "SPC") {
    const res = await fetch(`${ONTOLOGY_BASE}/api/v1/lots`, { cache: "no-store" });
    if (!res.ok) throw new Error(`lots ${res.status}`);
    const lots = await res.json() as Record<string, unknown>[];
    const items = lots.map((l) => ({ id: l.lot_id as string, status: l.status as string }));
    return NextResponse.json({ type, total: items.length, items });
  }

  // EC / FDC → tool-bound → proxy tools list
  if (type === "EC" || type === "FDC") {
    const res = await fetch(`${ONTOLOGY_BASE}/api/v1/tools`, { cache: "no-store" });
    if (!res.ok) throw new Error(`tools ${res.status}`);
    const tools = await res.json() as Record<string, unknown>[];
    const items = tools.map((t) => ({
      id:     t.tool_id as string,
      name:   TOOL_NAMES[t.tool_id as string] ?? (t.tool_id as string),
      status: STATUS_MAP[t.status as string] ?? (t.status as string),
    }));
    return NextResponse.json({ type, total: items.length, items });
  }

  // OCAP → events that triggered an OCAP, return distinct lot+step combos
  if (type === "OCAP") {
    const res = await fetch(`${ONTOLOGY_BASE}/api/v1/events?limit=500`, { cache: "no-store" });
    if (!res.ok) throw new Error(`events ${res.status}`);
    const events = await res.json() as Record<string, unknown>[];
    const seen = new Set<string>();
    const items: { id: string; lotID: string; step: string; eventTime: string }[] = [];
    for (const ev of events) {
      if (!ev.ocapId) continue;
      const key = `${ev.lotID}|${ev.step}`;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({
        id:        key,
        lotID:     ev.lotID     as string,
        step:      ev.step      as string,
        eventTime: ev.eventTime as string,
      });
    }
    return NextResponse.json({ type, total: items.length, items });
  }

  // RECIPE / APC → distinct IDs from recent events
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/events?limit=500`, { cache: "no-store" });
  if (!res.ok) throw new Error(`events ${res.status}`);
  const events = await res.json() as Record<string, unknown>[];
  const idKey  = type === "RECIPE" ? "recipeID" : "apcID";
  const seen   = new Set<string>();
  for (const ev of events) {
    const id = ev[idKey] as string | undefined;
    if (id) seen.add(id);
  }
  const items = Array.from(seen).sort().map((id) => ({ id }));
  return NextResponse.json({ type, total: items.length, items });
}

/**
 * Topology RUNS aggregate — feeds the new TopologyWorkbench (multi-lane trace,
 * 28-day scrubber). One RUN = one completed process step (the simulator's
 * `events` collection already yields tuples of (eventTime, lot, tool, step,
 * recipe, apc, spc_status, fdc_classification) — i.e. each event IS a run).
 *
 * Filters supported:
 *   from, to       — ISO timestamps (window). Defaults to last 28 days → now.
 *   focus_kind     — lot|tool|recipe|apc|step|fdc|spc (optional)
 *   focus_id       — id corresponding to focus_kind (optional)
 *   limit          — max runs (cap 500, simulator's hard limit)
 *
 * Returns: { runs: RunRecord[], window: {from, to}, kindStats: {kind: count} }
 */
async function getTopologyRuns(searchParams: URLSearchParams) {
  const limit     = Math.min(Number(searchParams.get("limit") ?? "500"), 500);
  const focusKind = (searchParams.get("focus_kind") ?? "").toLowerCase();
  const focusId   = searchParams.get("focus_id") ?? "";

  // Default window = last 24 hours.
  // Was 28d, but combined with limit=500 it caused Topology to sample
  // 500 events from a 28d window while Health Timeline shows 24h —
  // visually they looked like inconsistent data sources. Both now
  // default to 24h so a tool focus shows the same window of activity.
  const now      = Date.now();
  const fromMs   = searchParams.get("from")
                  ? Date.parse(searchParams.get("from") as string)
                  : now - 24 * 60 * 60 * 1000;
  const toMs     = searchParams.get("to")
                  ? Date.parse(searchParams.get("to") as string)
                  : now;
  const fromIso  = new Date(fromMs).toISOString();
  const toIso    = new Date(toMs).toISOString();

  // Push tool/lot filter to simulator (other kinds get filtered in Node)
  const qs = new URLSearchParams({ start_time: fromIso, limit: String(limit) });
  if (focusKind === "tool") qs.set("toolID", focusId);
  if (focusKind === "lot")  qs.set("lotID",  focusId);

  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/events?${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`events ${res.status}`);
  const raw = await res.json() as Record<string, unknown>[];

  const statusOf = (e: Record<string, unknown>): "ok" | "warn" | "alarm" => {
    const spc = (e.spc_status as string) ?? "";
    const fdc = (e.fdc_classification as string) ?? "";
    if (spc === "FAIL" || (fdc && fdc !== "NORMAL")) return "alarm";
    if (spc === "OOC")  return "warn";
    return "ok";
  };

  const runs = raw
    .filter((e) => {
      const t = Date.parse(e.eventTime as string);
      if (Number.isFinite(t) && (t < fromMs || t > toMs)) return false;
      if (!focusKind || !focusId) return true;
      switch (focusKind) {
        case "lot":    return e.lotID    === focusId;
        case "tool":   return e.toolID   === focusId;
        case "recipe": return e.recipeID === focusId;
        case "apc":    return e.apcID    === focusId;
        case "step":   return e.step     === focusId;
        case "fdc":    return (e.fdc_classification ?? "") === focusId;
        case "spc":    return (e.spc_status ?? "") === focusId;
        default:       return true;
      }
    })
    .map((e, i) => ({
      id:        `${e.toolID ?? ""}-${e.lotID ?? ""}-${e.step ?? ""}-${i}`,
      eventTime: e.eventTime as string,
      lotID:     (e.lotID    as string) ?? "",
      toolID:    (e.toolID   as string) ?? "",
      step:      (e.step     as string) ?? "",
      recipeID:  (e.recipeID as string) ?? "",
      apcID:     (e.apcID    as string) ?? "",
      fdcID:     (e.fdc_classification as string) ?? "",
      spcID:     (e.spc_status         as string) ?? "",
      status:    statusOf(e),
    }));

  // Sort oldest-first so timeline scrubber gets natural ordering
  runs.sort((a, b) => Date.parse(a.eventTime) - Date.parse(b.eventTime));

  const kindStats = {
    tool:   new Set(runs.map((r) => r.toolID).filter(Boolean)).size,
    lot:    new Set(runs.map((r) => r.lotID).filter(Boolean)).size,
    step:   new Set(runs.map((r) => r.step).filter(Boolean)).size,
    recipe: new Set(runs.map((r) => r.recipeID).filter(Boolean)).size,
    apc:    new Set(runs.map((r) => r.apcID).filter(Boolean)).size,
    fdc:    new Set(runs.map((r) => r.fdcID).filter(Boolean)).size,
    spc:    new Set(runs.map((r) => r.spcID).filter(Boolean)).size,
  };

  return NextResponse.json({
    runs,
    window:    { from: fromIso, to: toIso },
    kindStats,
    truncated: raw.length >= limit,
  });
}


async function getTopologySnapshot(searchParams: URLSearchParams) {
  const lotId     = searchParams.get("lot") ?? "";
  const step      = searchParams.get("step") ?? "";
  const eventTime = searchParams.get("eventTime") ?? "";

  if (!lotId || !step || !eventTime) {
    return NextResponse.json({ error: "lot, step, eventTime are required" }, { status: 400 });
  }

  const base = `${ONTOLOGY_BASE}/api/v1/context/query`
    + `?targetID=${encodeURIComponent(lotId)}`
    + `&step=${encodeURIComponent(step)}`
    + `&eventTime=${encodeURIComponent(eventTime)}`;

  const [dcRes, spcRes, apcRes, recipeRes, toolsRes, ecRes, fdcRes, ocapRes] = await Promise.allSettled([
    fetch(`${base}&objectName=DC`,     { cache: "no-store" }),
    fetch(`${base}&objectName=SPC`,    { cache: "no-store" }),
    fetch(`${base}&objectName=APC`,    { cache: "no-store" }),
    fetch(`${base}&objectName=RECIPE`, { cache: "no-store" }),
    fetch(`${ONTOLOGY_BASE}/api/v1/tools`, { cache: "no-store" }),
    fetch(`${base}&objectName=EC`,     { cache: "no-store" }),
    fetch(`${base}&objectName=FDC`,    { cache: "no-store" }),
    fetch(`${base}&objectName=OCAP`,   { cache: "no-store" }),
  ]);

  const safe = async (r: PromiseSettledResult<Response>) => {
    if (r.status !== "fulfilled" || !r.value.ok) return null;
    return r.value.json().catch(() => null);
  };

  const [dcRaw, spcRaw, apcRaw, recipeRaw, tools, ecRaw, fdcRaw, ocapRaw] = await Promise.all([
    safe(dcRes), safe(spcRes), safe(apcRes), safe(recipeRes), safe(toolsRes),
    safe(ecRes), safe(fdcRes), safe(ocapRes),
  ]);

  // ── Translate parameter keys → labelled objects ──────────────────────────
  const dc = dcRaw
    ? { ...dcRaw, ...addLabels((dcRaw as Record<string, unknown>).parameters as Record<string, unknown> ?? {}, DC_LABELS) }
    : null;

  const spc = spcRaw ? enrichSpc(spcRaw as Record<string, unknown>) : null;

  const apc = apcRaw
    ? { ...apcRaw, ...addLabels((apcRaw as Record<string, unknown>).parameters as Record<string, unknown> ?? {}, APC_LABELS) }
    : null;

  const recipe = recipeRaw
    ? { ...recipeRaw, ...addLabels((recipeRaw as Record<string, unknown>).parameters as Record<string, unknown> ?? {}, RECIPE_LABELS) }
    : null;

  // ── EC: enrich component_health with labels ───────────────────────────────
  const ec = ecRaw ? {
    ...(ecRaw as Record<string, unknown>),
    health_labels: EC_HEALTH_LABELS,
  } : null;

  // ── FDC: enrich with Chinese fault description ────────────────────────────
  const fdc = fdcRaw ? {
    ...(fdcRaw as Record<string, unknown>),
    fault_description: FDC_FAULT_DESCRIPTIONS[(fdcRaw as Record<string, unknown>).fault_code as string] ?? "",
  } : null;

  // ── OCAP: pass through as-is (all fields are already human-readable) ──────
  const ocap = ocapRaw as Record<string, unknown> | null;

  // ── Resolve tool ─────────────────────────────────────────────────────────
  const toolId = (spcRaw as Record<string, unknown> | null)?.toolID
              ?? (dcRaw  as Record<string, unknown> | null)?.toolID
              ?? null;
  const tool = toolId && Array.isArray(tools)
    ? normalizeTool((tools as Record<string, unknown>[]).find((t) => t.tool_id === toolId) ?? {})
    : null;

  return NextResponse.json({ lot_id: lotId, step, eventTime, tool, dc, spc, apc, recipe, ec, fdc, ocap });
}

/** Step-centric DC timeseries — proxy to OntologySimulator /analytics/step-dc */
async function getStepDcTimeseries(searchParams: URLSearchParams) {
  const step      = (searchParams.get("step") ?? "").toUpperCase();
  const paramRaw  = searchParams.get("parameter") ?? "";
  const limit     = searchParams.get("limit") ?? "100";
  const start     = searchParams.get("start") ?? "";
  const end       = searchParams.get("end")   ?? "";

  if (!step || !paramRaw) {
    return NextResponse.json({ error: "step and parameter are required" }, { status: 400 });
  }

  // Resolve display name → sensor key
  const sensorKey = PARAM_KEY_MAP[paramRaw] ?? paramRaw;
  const label     = DC_LABELS[sensorKey];

  const qs = new URLSearchParams({ step, parameter: sensorKey, limit });
  if (start) qs.set("start", start);
  if (end)   qs.set("end", end);

  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/analytics/step-dc?${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`step-dc ${res.status}`);
  const body = await res.json() as Record<string, unknown>;

  return NextResponse.json({
    ...body,
    parameter_display: paramRaw,
    sensor_key:        sensorKey,
    unit:              label?.unit  ?? "",
    group:             label?.group ?? "",
  });
}

/** Step-centric SPC chart timeseries — proxy to OntologySimulator /analytics/step-spc */
async function getStepSpcChart(searchParams: URLSearchParams) {
  const step       = (searchParams.get("step") ?? "").toUpperCase();
  const chartName  = searchParams.get("chart_name") ?? "";
  const limit      = searchParams.get("limit") ?? "100";
  const start      = searchParams.get("start") ?? "";
  const end        = searchParams.get("end")   ?? "";

  if (!step || !chartName) {
    return NextResponse.json({ error: "step and chart_name are required" }, { status: 400 });
  }

  const qs = new URLSearchParams({ step, chart_name: chartName, limit });
  if (start) qs.set("start", start);
  if (end)   qs.set("end", end);

  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/analytics/step-spc?${qs}`, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`step-spc ${res.status}: ${text.slice(0, 200)}`);
  }
  const body = await res.json() as Record<string, unknown>;

  const chartMeta = SPC_CHART_LABELS[chartName];
  return NextResponse.json({
    ...body,
    chart_display_name: chartMeta?.name   ?? chartName,
    sensor:             chartMeta?.sensor ?? "",
  });
}

/** Proxy GET /api/v1/objects — list all object types with parameter counts */
async function getObjectCatalog() {
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/objects`, { cache: "no-store" });
  if (!res.ok) throw new Error(`objects ${res.status}`);
  return NextResponse.json(await res.json());
}

/** Proxy GET /api/v1/objects/{name}/schema */
async function getObjectSchema(objectName: string) {
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/objects/${encodeURIComponent(objectName)}/schema`, { cache: "no-store" });
  if (!res.ok) {
    if (res.status === 404) return NextResponse.json({ error: `Object '${objectName}' not found` }, { status: 404 });
    throw new Error(`objects/schema ${res.status}`);
  }
  return NextResponse.json(await res.json());
}

/** Proxy POST /api/v1/objects/query */
async function queryObjectParameter(body: unknown) {
  const res = await fetch(`${ONTOLOGY_BASE}/api/v1/objects/query`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
    cache:   "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`objects/query ${res.status}: ${text.slice(0, 300)}`);
  }
  return NextResponse.json(await res.json());
}

async function getLotObjects(lotId: string, objectName: string, step?: string) {
  const stepParam = step ? `&step=${encodeURIComponent(step)}` : "";
  const url = `${ONTOLOGY_BASE}/api/v1/analytics/history?targetID=${lotId}&objectName=${objectName}&limit=1${stepParam}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`analytics/history ${res.status}`);
  const docs = await res.json() as Record<string, unknown>[];
  return NextResponse.json({ lot_id: lotId, objectName, step, data: docs });
}

// ---------------------------------------------------------------------------
// Main dispatcher
// ---------------------------------------------------------------------------

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const sp = req.nextUrl.searchParams;

  try {
    // Direct simulator proxy: /api/ontology/process/info → /api/v1/process/info
    if (path.length === 2 && path[0] === "process" && path[1] === "info") {
      const res = await fetch(`${ONTOLOGY_BASE}/api/v1/process/info?${sp}`, { cache: "no-store" });
      return NextResponse.json(await res.json());
    }
    // Direct simulator proxy: /api/ontology/process/summary → /api/v1/process/summary
    if (path.length === 2 && path[0] === "process" && path[1] === "summary") {
      const res = await fetch(`${ONTOLOGY_BASE}/api/v1/process/summary?${sp}`, { cache: "no-store" });
      return NextResponse.json(await res.json());
    }
    // Direct simulator proxy: /api/ontology/tools → /api/v1/tools
    if (path.length === 1 && path[0] === "tools") {
      const res = await fetch(`${ONTOLOGY_BASE}/api/v1/tools`, { cache: "no-store" });
      return NextResponse.json(await res.json());
    }

    if (path.length === 1 && path[0] === "equipment")
      return await getEquipmentList();

    if (path.length === 2 && path[0] === "equipment")
      return await getEquipmentOne(path[1]);

    if (path.length === 4 && path[0] === "equipment" && path[2] === "dc" && path[3] === "timeseries")
      return await getDcTimeseries(path[1], sp);

    if (path.length === 1 && path[0] === "events")
      return await getEvents(sp);

    if (path.length === 1 && path[0] === "lots")
      return await getLots();

    if (path.length === 3 && path[0] === "lots" && path[2] === "objects")
      return await getLotObjects(path[1], sp.get("objectName") ?? "DC", sp.get("step") ?? undefined);

    if (path.length === 1 && path[0] === "topology")
      return await getTopologySnapshot(sp);

    // GET /api/ontology/topology/runs?from=&to=&focus_kind=&focus_id=&limit=
    if (path.length === 2 && path[0] === "topology" && path[1] === "runs")
      return await getTopologyRuns(sp);

    // GET /api/ontology/objects?type=RECIPE|APC
    if (path.length === 1 && path[0] === "objects")
      return await getObjectList((sp.get("type") ?? "RECIPE").toUpperCase());

    // GET /api/ontology/analytics/step-dc?step=STEP_007&parameter=Chamber+Press
    if (path.length === 2 && path[0] === "analytics" && path[1] === "step-dc")
      return await getStepDcTimeseries(sp);

    // GET /api/ontology/analytics/step-spc?step=STEP_007&chart_name=xbar_chart
    if (path.length === 2 && path[0] === "analytics" && path[1] === "step-spc")
      return await getStepSpcChart(sp);

    // GET /api/ontology/object-catalog → list all object types
    if (path.length === 1 && path[0] === "object-catalog")
      return await getObjectCatalog();

    // GET /api/ontology/object-schema/APC → schema for one object
    if (path.length === 2 && path[0] === "object-schema")
      return await getObjectSchema(path[1]);

    return NextResponse.json({ error: `Unknown path: /${path.join("/")}` }, { status: 404 });

  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: `Ontology adapter error: ${message}` }, { status: 503 });
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  try {
    // POST /api/ontology/object-query
    if (path.length === 1 && path[0] === "object-query") {
      const body = await req.json();
      return await queryObjectParameter(body);
    }
    return NextResponse.json({ error: `Unknown POST path: /${path.join("/")}` }, { status: 404 });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: `Ontology adapter error: ${message}` }, { status: 503 });
  }
}
