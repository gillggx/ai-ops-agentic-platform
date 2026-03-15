"use client";
import { useEffect, useState } from "react";
import { MachineState } from "@/lib/types";
import { TopoNode } from "@/components/TopologyView";
import { LogType } from "@/hooks/useConsole";

function getApiUrl() {
  if (typeof window === "undefined") return "http://localhost:8001/api/v1";
  const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return isLocal ? `http://${window.location.hostname}:8001/api/v1` : `${window.location.origin}/simulator-api/api/v1`;
}

// ── URL builder ──────────────────────────────────────────────
function buildUrl(node: TopoNode, machine: MachineState, eventTime: string | null): string | null {
  const step = machine.step;
  const et   = eventTime ?? machine.lastEvent;
  if (!step || !et) return null;
  const targetID = node === "LOT" ? (machine.lotId ?? machine.id) : machine.id;
  return `${getApiUrl()}/context/query?${new URLSearchParams({ targetID, step, objectName: node, eventTime: et })}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
}

// ── Sensor/param maps ────────────────────────────────────────

interface SensorDef { key: string; label: string; unit: string }
interface SensorGroup { title: string; color: string; sensors: SensorDef[] }

const DC_GROUPS: SensorGroup[] = [
  {
    title: "Vacuum",
    color: "sky",
    sensors: [
      { key: "chamber_pressure",       label: "Chamber Press",    unit: "mTorr" },
      { key: "foreline_pressure",      label: "Foreline Press",   unit: "mTorr" },
      { key: "loadlock_pressure",      label: "Load Lock Press",  unit: "mTorr" },
      { key: "transfer_pressure",      label: "Transfer Press",   unit: "mTorr" },
      { key: "throttle_position_pct",  label: "Throttle Pos",     unit: "%" },
      { key: "gate_valve_position_pct",label: "Gate Valve Pos",   unit: "%" },
    ],
  },
  {
    title: "Thermal",
    color: "orange",
    sensors: [
      { key: "esc_zone1_temp",   label: "ESC Zone1 Temp",   unit: "°C" },
      { key: "esc_zone2_temp",   label: "ESC Zone2 Temp",   unit: "°C" },
      { key: "esc_zone3_temp",   label: "ESC Zone3 Temp",   unit: "°C" },
      { key: "chuck_temp_c",     label: "Chuck Temp",        unit: "°C" },
      { key: "wall_temp_c",      label: "Wall Temp",         unit: "°C" },
      { key: "ceiling_temp_c",   label: "Ceiling Temp",      unit: "°C" },
      { key: "gas_inlet_temp_c", label: "Gas Inlet Temp",    unit: "°C" },
      { key: "exhaust_temp_c",   label: "Exhaust Temp",      unit: "°C" },
    ],
  },
  {
    title: "Power",
    color: "violet",
    sensors: [
      { key: "rf_forward_power", label: "RF Forward Power",  unit: "W" },
      { key: "reflected_power",  label: "Reflected Power",   unit: "W" },
      { key: "bias_power_lf_w",  label: "Bias Power LF",     unit: "W" },
      { key: "bias_refl_lf_w",   label: "Bias Refl LF",      unit: "W" },
      { key: "bias_voltage_v",   label: "Bias Voltage",      unit: "V" },
      { key: "bias_current_a",   label: "Bias Current",      unit: "A" },
      { key: "source_freq_mhz",  label: "Source Freq",       unit: "MHz" },
      { key: "match_cap_c1_pf",  label: "Match Cap C1",      unit: "pF" },
    ],
  },
  {
    title: "Gas Flow",
    color: "emerald",
    sensors: [
      { key: "cf4_flow_sccm",        label: "CF4 Flow",         unit: "sccm" },
      { key: "o2_flow_sccm",         label: "O2 Flow",          unit: "sccm" },
      { key: "ar_flow_sccm",         label: "Ar Flow",          unit: "sccm" },
      { key: "n2_flow_sccm",         label: "N2 Flow",          unit: "sccm" },
      { key: "helium_coolant_press", label: "He Coolant Press",  unit: "Torr" },
      { key: "chf3_flow_sccm",       label: "CHF3 Flow",        unit: "sccm" },
      { key: "c4f8_flow_sccm",       label: "C4F8 Flow",        unit: "sccm" },
      { key: "total_flow_sccm",      label: "Total Flow",       unit: "sccm" },
    ],
  },
];

const APC_GROUPS: SensorGroup[] = [
  {
    title: "Run-to-Run",
    color: "sky",
    sensors: [
      { key: "etch_time_offset",   label: "Etch Time Offset",  unit: "s" },
      { key: "rf_power_bias",      label: "RF Power Bias",     unit: "" },
      { key: "gas_flow_comp",      label: "Gas Flow Comp",     unit: "sccm" },
      { key: "model_intercept",    label: "Model Intercept",   unit: "" },
    ],
  },
  {
    title: "Process Setpoints",
    color: "orange",
    sensors: [
      { key: "target_cd_nm",       label: "Target CD",         unit: "nm" },
      { key: "target_epd_s",       label: "Target EPD",        unit: "s" },
      { key: "etch_rate_pred",     label: "Etch Rate Pred",    unit: "nm/min" },
      { key: "uniformity_pct",     label: "Uniformity",        unit: "%" },
    ],
  },
  {
    title: "Feed-Forward",
    color: "violet",
    sensors: [
      { key: "ff_correction",      label: "FF Correction",     unit: "" },
      { key: "ff_weight",          label: "FF Weight",         unit: "" },
      { key: "ff_alpha",           label: "FF Alpha",          unit: "" },
      { key: "lot_weight",         label: "Lot Weight",        unit: "" },
    ],
  },
  {
    title: "Feedback & Model",
    color: "emerald",
    sensors: [
      { key: "fb_correction",      label: "FB Correction",     unit: "" },
      { key: "fb_alpha",           label: "FB Alpha",          unit: "" },
      { key: "model_r2_score",     label: "Model R²",          unit: "" },
      { key: "stability_index",    label: "Stability Index",   unit: "" },
      { key: "prediction_error_nm",label: "Prediction Error",  unit: "nm" },
      { key: "convergence_idx",    label: "Convergence Idx",   unit: "" },
      { key: "reg_lambda",         label: "Reg λ",             unit: "" },
      { key: "response_factor",    label: "Response Factor",   unit: "" },
    ],
  },
];

const RECIPE_GROUPS: SensorGroup[] = [
  {
    title: "Etch Process",
    color: "sky",
    sensors: [
      { key: "etch_time_s",          label: "Etch Time",         unit: "s" },
      { key: "target_thickness_nm",  label: "Target Thickness",  unit: "nm" },
      { key: "etch_rate_nm_per_s",   label: "Etch Rate",         unit: "nm/s" },
      { key: "cd_bias_nm",           label: "CD Bias",           unit: "nm" },
      { key: "over_etch_pct",        label: "Over-Etch",         unit: "%" },
    ],
  },
  {
    title: "Chamber Conditions",
    color: "orange",
    sensors: [
      { key: "process_pressure_mtorr",label: "Process Press",    unit: "mTorr" },
      { key: "base_pressure_mtorr",  label: "Base Press",        unit: "mTorr" },
      { key: "chamber_temp_c",       label: "Chamber Temp",      unit: "°C" },
      { key: "wall_temp_c",          label: "Wall Temp",         unit: "°C" },
    ],
  },
  {
    title: "Gas Setpoints",
    color: "emerald",
    sensors: [
      { key: "cf4_setpoint_sccm",    label: "CF4 Setpoint",      unit: "sccm" },
      { key: "o2_setpoint_sccm",     label: "O2 Setpoint",       unit: "sccm" },
      { key: "ar_setpoint_sccm",     label: "Ar Setpoint",       unit: "sccm" },
      { key: "he_setpoint_sccm",     label: "He Setpoint",       unit: "sccm" },
    ],
  },
  {
    title: "RF Power",
    color: "violet",
    sensors: [
      { key: "source_power_w",       label: "Source Power",      unit: "W" },
      { key: "bias_power_w",         label: "Bias Power",        unit: "W" },
      { key: "source_freq_mhz",      label: "Source Freq",       unit: "MHz" },
      { key: "bias_freq_khz",        label: "Bias Freq",         unit: "kHz" },
      { key: "epd_threshold_au",     label: "EPD Threshold",     unit: "AU" },
      { key: "min_etch_time_s",      label: "Min Etch Time",     unit: "s" },
      { key: "max_etch_time_s",      label: "Max Etch Time",     unit: "s" },
    ],
  },
];

// ── JSON syntax highlighting ─────────────────────────────────
function syntaxHighlight(obj: Record<string, unknown>): string {
  const raw = JSON.stringify(obj, null, 2)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return raw
    // keys
    .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
    // string values
    .replace(/: "([^"]*)"/g, ': <span class="json-str">"$1"</span>')
    // numeric values (including negative/decimal)
    .replace(/: (-?[0-9]+\.?[0-9]*)/g, ': <span class="json-num">$1</span>');
}

function RawCodeBlock({ params }: { params: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 rounded overflow-hidden border border-slate-700">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-1.5 bg-[#1e293b] text-[10px] font-mono font-semibold text-slate-300 hover:bg-[#273548] transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none"
               stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
          </svg>
          RAW PAYLOAD (JSON)
        </span>
        <span className="text-slate-500">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="bg-[#1e293b] px-4 py-3 overflow-x-auto">
          <pre
            className="text-[11px] font-mono leading-relaxed text-slate-300 m-0 whitespace-pre"
            dangerouslySetInnerHTML={{ __html: syntaxHighlight(params) }}
          />
        </div>
      )}
    </div>
  );
}

// ── Group badge color ─────────────────────────────────────────
const GROUP_TAG: Record<string, string> = {
  sky:     "bg-sky-50 text-sky-600 border-sky-200",
  orange:  "bg-orange-50 text-orange-600 border-orange-200",
  violet:  "bg-violet-50 text-violet-600 border-violet-200",
  emerald: "bg-emerald-50 text-emerald-600 border-emerald-200",
};

// ── Sub-components ───────────────────────────────────────────

function MetaHeader({ data, node }: { data: Record<string, unknown>; node: TopoNode }) {
  const ts = (data.last_updated_time ?? data.eventTime) as string | undefined;
  const timeStr = ts ? fmtTime(ts) : "—";
  const objectName = (data.objectName as string) ?? node;
  const step       = (data.step as string)       ?? "—";
  const lotID      = (data.lotID as string)       ?? "—";
  const toolID     = (data.toolID as string)      ?? "—";
  const mode       = (data.mode as string)        ?? null;

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mb-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold tracking-widest px-2 py-0.5 rounded border
                           bg-blue-50 text-blue-600 border-blue-200">
            {objectName}
          </span>
          <span className="text-[12px] font-mono font-semibold text-slate-700">{step}</span>
          {mode && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600
                             border border-emerald-200">
              {mode}
            </span>
          )}
        </div>
        <span className="text-[11px] font-mono text-slate-400">{timeStr}</span>
      </div>
      <div className="flex justify-between text-[11px]">
        <span className="text-slate-500">
          Lot <span className="font-mono font-semibold text-slate-700">{lotID}</span>
        </span>
        <span className="text-slate-500">
          Tool <span className="font-mono font-semibold text-slate-700">{toolID}</span>
        </span>
      </div>
    </div>
  );
}

function ParamRow({ label, value, unit }: { label: string; value: number | null; unit: string }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-slate-500 text-[11px] truncate pr-2">{label}</span>
      <span className="font-mono font-bold text-slate-800 text-[11px] shrink-0 tabular-nums">
        {value !== null ? value.toFixed(4) : "—"}
        {unit && <span className="ml-1 font-normal text-slate-400 text-[10px]">{unit}</span>}
      </span>
    </div>
  );
}

function SensorGroupBlock({
  group,
  params,
}: {
  group: SensorGroup;
  params: Record<string, unknown>;
}) {
  return (
    <div className="mb-4">
      <div className={`inline-flex items-center text-[10px] font-semibold tracking-widest
                       px-1.5 py-0.5 rounded border mb-1.5 ${GROUP_TAG[group.color] ?? ""}`}>
        {group.title.toUpperCase()}
      </div>
      <div className="divide-y divide-slate-100">
        {group.sensors.map(s => {
          const raw = params[s.key];
          const val = typeof raw === "number" ? raw : (typeof raw === "string" ? parseFloat(raw) : null);
          return <ParamRow key={s.key} label={s.label} value={isNaN(val as number) ? null : val} unit={s.unit} />;
        })}
      </div>
    </div>
  );
}

function parseParams(raw: unknown): Record<string, unknown> {
  if (typeof raw === "string") return JSON.parse(raw);
  if (typeof raw === "object" && raw !== null) return raw as Record<string, unknown>;
  return {};
}

// DC renderer
function DCBody({ data }: { data: Record<string, unknown> }) {
  const params = parseParams(data.parameters);
  return (
    <>
      {DC_GROUPS.map(g => <SensorGroupBlock key={g.title} group={g} params={params} />)}
      <RawCodeBlock params={params} />
    </>
  );
}

// APC renderer
function APCBody({ data }: { data: Record<string, unknown> }) {
  const params = parseParams(data.parameters);
  return (
    <>
      {APC_GROUPS.map(g => <SensorGroupBlock key={g.title} group={g} params={params} />)}
      <RawCodeBlock params={params} />
    </>
  );
}

// RECIPE renderer
function RecipeBody({ data }: { data: Record<string, unknown> }) {
  const params = parseParams(data.parameters);
  return (
    <>
      {RECIPE_GROUPS.map(g => <SensorGroupBlock key={g.title} group={g} params={params} />)}
      <RawCodeBlock params={params} />
    </>
  );
}

// ── SPC mini trend chart ─────────────────────────────────────

type SpcHistSnapshot = {
  charts: Record<string, { value: number; ucl: number; lcl: number }>;
  spc_status: string;
};

function MiniTrendChart({
  chartKey,
  history,
  ucl,
  lcl,
}: {
  chartKey: string;
  history: SpcHistSnapshot[] | null;
  ucl: number;
  lcl: number;
}) {
  if (!history || history.length === 0) return null;
  const values = history
    .map(d => d.charts?.[chartKey]?.value)
    .filter((v): v is number => v !== undefined);
  if (values.length < 2) return null;

  const W = 280, H = 54, PL = 6, PR = 4, PT = 6, PB = 6;
  const iW = W - PL - PR;
  const iH = H - PT - PB;
  const margin = (ucl - lcl) * 0.35;
  const yMin = lcl - margin;
  const yMax = ucl + margin;
  const yRange = yMax - yMin || 1;
  const n = values.length;
  const toX = (i: number) => PL + (n === 1 ? iW / 2 : (i / (n - 1)) * iW);
  const toY = (v: number) => PT + (1 - (v - yMin) / yRange) * iH;
  const pts = values.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
  const yU = toY(ucl), yL = toY(lcl), yC = toY((ucl + lcl) / 2);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="block overflow-visible">
      {/* OOC bands */}
      <rect x={PL} y={PT} width={iW} height={Math.max(0, yU - PT)} fill="#fef3c7" fillOpacity="0.4" />
      <rect x={PL} y={yL} width={iW} height={Math.max(0, H - PB - yL)} fill="#fef3c7" fillOpacity="0.4" />
      {/* Center line */}
      <line x1={PL} y1={yC} x2={W - PR} y2={yC} stroke="#cbd5e1" strokeWidth="0.5" strokeDasharray="3,2" />
      {/* UCL / LCL */}
      <line x1={PL} y1={yU} x2={W - PR} y2={yU} stroke="#f59e0b" strokeWidth="1" strokeDasharray="4,2" />
      <line x1={PL} y1={yL} x2={W - PR} y2={yL} stroke="#f59e0b" strokeWidth="1" strokeDasharray="4,2" />
      {/* Polyline */}
      <polyline points={pts} fill="none" stroke="#6366f1" strokeWidth="1.3" strokeLinejoin="round" />
      {/* Dots */}
      {values.map((v, i) => {
        const ooc = v < lcl || v > ucl;
        return (
          <circle key={i} cx={toX(i)} cy={toY(v)} r={ooc ? 3 : 2}
            fill={ooc ? "#f59e0b" : "#6366f1"}
            stroke={ooc ? "#fff" : "none"} strokeWidth="0.8" />
        );
      })}
    </svg>
  );
}

// SPC renderer
function SPCBody({ data }: { data: Record<string, unknown> }) {
  const charts = data.charts as Record<string, { value: number; ucl: number; lcl: number }> | undefined;
  const status = data.spc_status as string;
  const isOOC  = status === "OOC";
  const toolID = data.toolID as string | undefined;

  const [history, setHistory] = useState<SpcHistSnapshot[] | null>(null);
  const [histLoading, setHistLoading] = useState(false);

  useEffect(() => {
    if (!toolID) return;
    setHistLoading(true);
    fetch(`${getApiUrl()}/analytics/history?targetID=${encodeURIComponent(toolID)}&objectName=SPC&limit=20`)
      .then(r => r.json())
      .then((docs: SpcHistSnapshot[]) => setHistory(docs))
      .catch(() => setHistory(null))
      .finally(() => setHistLoading(false));
  }, [toolID]);

  const chartLabels: Record<string, { name: string; unit: string }> = {
    xbar_chart: { name: "Chamber Press", unit: "mTorr" },
    r_chart:    { name: "Bias Voltage",  unit: "V"     },
    s_chart:    { name: "ESC Zone1 Temp",unit: "°C"    },
    p_chart:    { name: "CF4 Flow",      unit: "sccm"  },
    c_chart:    { name: "Source Pwr HF", unit: "W"     },
  };

  return (
    <>
      <div className={`flex items-center justify-between rounded-lg px-3 py-2 mb-4 border
        ${isOOC
          ? "bg-amber-50 border-amber-300 text-amber-700"
          : "bg-emerald-50 border-emerald-300 text-emerald-700"}`}>
        <span className="text-[11px] font-semibold tracking-wide">
          {isOOC ? "⚠ OUT OF CONTROL" : "✓ IN CONTROL"}
        </span>
        <span className="text-[11px] font-mono font-bold">{status}</span>
      </div>

      {/* Current reading table */}
      <div className="mb-4">
        <div className={`inline-flex items-center text-[10px] font-semibold tracking-widest
                         px-1.5 py-0.5 rounded border mb-1.5 ${GROUP_TAG["violet"]}`}>
          CONTROL CHARTS
        </div>
        <div className="flex text-[10px] text-slate-400 font-semibold mb-1 px-0.5">
          <span className="flex-1">SENSOR</span>
          <span className="w-20 text-right">VALUE</span>
          <span className="w-14 text-right">LCL</span>
          <span className="w-14 text-right">UCL</span>
          <span className="w-8 text-right">OK</span>
        </div>
        <div className="divide-y divide-slate-100">
          {charts && Object.entries(charts).map(([key, c]) => {
            const inControl = c.value >= c.lcl && c.value <= c.ucl;
            const lbl = chartLabels[key];
            return (
              <div key={key} className="flex items-center py-1 px-0.5 text-[11px]">
                <span className="flex-1 text-slate-500 truncate">
                  {lbl ? lbl.name : key}
                  {lbl && <span className="ml-1 text-[9px] text-slate-400">({lbl.unit})</span>}
                </span>
                <span className="w-20 text-right font-mono font-bold text-slate-800 tabular-nums">
                  {c.value.toFixed(2)}
                </span>
                <span className="w-14 text-right font-mono text-slate-400 tabular-nums">
                  {c.lcl.toFixed(1)}
                </span>
                <span className="w-14 text-right font-mono text-slate-400 tabular-nums">
                  {c.ucl.toFixed(1)}
                </span>
                <span className={`w-8 text-right font-semibold ${inControl ? "text-emerald-500" : "text-amber-600"}`}>
                  {inControl ? "✓" : "✗"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Historical trend charts */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className={`inline-flex items-center text-[10px] font-semibold tracking-widest
                           px-1.5 py-0.5 rounded border ${GROUP_TAG["sky"]}`}>
            TREND HISTORY
          </div>
          {histLoading && (
            <span className="text-[9px] text-slate-400 font-mono animate-pulse">loading…</span>
          )}
          {history && !histLoading && (
            <span className="text-[9px] text-slate-400 font-mono">{history.length} pts</span>
          )}
        </div>

        {!histLoading && history && history.length >= 2 && charts && (
          <div className="space-y-3">
            {Object.entries(charts).map(([key, c]) => {
              const lbl = chartLabels[key];
              const hasOOC = history.some(d => {
                const v = d.charts?.[key]?.value;
                return v !== undefined && (v < c.lcl || v > c.ucl);
              });
              return (
                <div key={key} className="bg-white rounded border border-slate-100 p-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-semibold text-slate-600">
                      {lbl ? lbl.name : key}
                      {lbl && <span className="ml-1 font-normal text-slate-400">({lbl.unit})</span>}
                    </span>
                    {hasOOC && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-200 font-semibold">
                        OOC
                      </span>
                    )}
                  </div>
                  <MiniTrendChart
                    chartKey={key}
                    history={history}
                    ucl={c.ucl}
                    lcl={c.lcl}
                  />
                  <div className="flex justify-between mt-1 text-[9px] font-mono text-slate-400">
                    <span>LCL {c.lcl.toFixed(1)}</span>
                    <span className="text-amber-500">— UCL/LCL</span>
                    <span>UCL {c.ucl.toFixed(1)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {!histLoading && (!history || history.length < 2) && (
          <div className="text-[10px] text-slate-400 font-mono text-center py-3 bg-slate-50 rounded border border-slate-100">
            No history yet — run more lots to build trend data.
          </div>
        )}
      </div>
    </>
  );
}

// Generic KV renderer for LOT / TOOL
function GenericBody({ data }: { data: Record<string, unknown> }) {
  const skip = new Set(["objectName", "toolID", "lotID", "step", "eventTime",
                        "last_updated_time", "updated_by", "objectID"]);
  const entries = Object.entries(data).filter(([k]) => !skip.has(k));
  return (
    <div className="divide-y divide-slate-100">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center justify-between py-1">
          <span className="text-slate-500 text-[11px] truncate pr-2">{k}</span>
          <span className="font-mono font-bold text-slate-800 text-[11px] truncate max-w-[140px]">
            {typeof v === "object" ? JSON.stringify(v) : String(v ?? "—")}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────

interface Props {
  machine: MachineState | null;
  activeNode: TopoNode | null;
  traceEventTime: string | null;
  addLog: (type: LogType, text: string) => void;
}

export default function RightInspector({ machine, activeNode, traceEventTime, addLog }: Props) {
  const [result,  setResult]  = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [label,   setLabel]   = useState<string | null>(null);

  useEffect(() => {
    if (!machine || !activeNode) return;

    const url = buildUrl(activeNode, machine, traceEventTime);
    if (!url) {
      setError("No step / eventTime — run a lot first.");
      setResult(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);
    setLabel(`${activeNode} · ${machine.step ?? machine.id}`);
    addLog("API_REQ", `GET ${url}`);

    fetch(url)
      .then(async r => {
        const data = await r.json() as Record<string, unknown>;
        if (cancelled) return;
        if (!r.ok) {
          const msg = (data?.detail as string) ?? `HTTP ${r.status}`;
          addLog("ERROR", `${activeNode} → ${msg}`);
          setError(msg);
        } else {
          addLog("API_RES", `${activeNode} OK (${Object.keys(data).length} fields)`);
          setResult(data);
        }
      })
      .catch(e => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        addLog("ERROR", `Fetch: ${msg}`);
        setError(msg);
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [machine?.id, machine?.step, machine?.lastEvent, activeNode, traceEventTime]);

  // SPC status derived from result (for header badge on DC node)
  const spcStatus = result && activeNode === "DC"
    ? (result.spc_status as string | undefined)
    : null;

  return (
    <div className="flex flex-col h-full bg-white overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-200 bg-slate-50/80 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <span className={[
            "px-2 py-0.5 rounded text-[10px] font-bold border",
            activeNode === "DC"
              ? "bg-indigo-100 text-indigo-700 border-indigo-200"
              : activeNode === "APC"
                ? "bg-sky-100 text-sky-700 border-sky-200"
                : activeNode === "SPC"
                  ? "bg-amber-100 text-amber-700 border-amber-200"
                  : "bg-slate-200 text-slate-600 border-slate-300",
          ].join(" ")}>
            {activeNode ?? "INSPECTOR"}
          </span>
          {spcStatus && (
            <span className={[
              "text-[9px] font-bold px-1.5 py-0.5 rounded border",
              spcStatus === "OOC"
                ? "bg-amber-100 text-amber-700 border-amber-200"
                : "bg-green-100 text-green-700 border-green-200",
            ].join(" ")}>
              SPC: {spcStatus === "OOC" ? "WARNING" : "IN CONTROL"}
            </span>
          )}
        </div>
        <h3 className="font-bold text-slate-800 text-base font-mono truncate">
          {label ?? "Ready"}
        </h3>
        {result && (
          <div className="mt-1.5 flex gap-3 text-[10px] text-slate-400 font-mono flex-wrap">
            {result.toolID ? <span>⚙️ {result.toolID as string}</span> : null}
            {result.lotID  ? <span>📦 {result.lotID  as string}</span> : null}
            {result.step   ? <span>🏷️ {result.step   as string}</span> : null}
          </div>
        )}
        {!result && !loading && (
          <div className="mt-1.5 text-[10px] text-slate-400 font-mono">
            {!machine ? "Select a machine…" : !activeNode ? "Click a topology node…" : ""}
          </div>
        )}
      </div>

      {/* Loading spinner */}
      {loading && (
        <div className="flex-1 flex flex-col items-center justify-center bg-slate-50/30">
          <svg className="animate-spin h-6 w-6 text-indigo-500 mb-3" xmlns="http://www.w3.org/2000/svg"
               fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
          </svg>
          <span className="text-xs font-mono text-slate-500">Executing API Query…</span>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="mx-3 mt-3 bg-amber-50 border border-amber-200 rounded p-2 text-[11px] text-amber-700 font-mono">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && !result && (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-400 bg-slate-50/50">
          <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
               className="mb-3 text-slate-300">
            <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
          </svg>
          <p className="text-[11px]">Select a node to inspect payload.</p>
        </div>
      )}

      {/* Body */}
      {result && !loading && (
        <div className="flex-1 overflow-y-auto px-3 py-3 bg-slate-50">
          {(() => {
            const node = activeNode!;
            return (
              <>
                <MetaHeader data={result} node={node} />
                {node === "DC"     && <DCBody     data={result} />}
                {node === "APC"    && <APCBody    data={result} />}
                {node === "RECIPE" && <RecipeBody data={result} />}
                {node === "SPC"    && <SPCBody    data={result} />}
                {(node === "LOT" || node === "TOOL") && <GenericBody data={result} />}
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
