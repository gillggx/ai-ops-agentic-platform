"use client";

/**
 * 手機 1d 設備詳情 — 頂部設備切換 chips＋健康分；5 項檢測狀態橫向捲動卡；
 * 分頁「健康趨勢／製程溯源」；健康度時間軸（lane 點圖）＋ SPC Chart 趨勢。
 * 資料走既有 /api/admin/fleet/equipment/{id}/{modules,timeline,spc-trace}。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { M, cardStyle } from "./tokens";

interface ModuleCard { key: string; state: "crit" | "warn" | "ok"; value: string; sub: string }
interface TimelineEvent { t: string; lane: string; severity: string; label: string; detail: string }
interface SpcChart { chart: string; values: number[]; times: string[]; ucl: number; lcl: number; target: number }
interface FleetEquipment { id: string; health: string; score: number; note: string }

const LANES: Array<[string, string]> = [
  ["ooc", "SPC OOC"], ["apc", "APC"], ["fdc", "FDC"], ["ec", "EC"],
  ["recipe", "Recipe 變更"], ["lot", "LOT"],
];
const SEV_DOT: Record<string, string> = {
  crit: M.crit, warn: M.med, info: "#3b6fd4", ok: M.ok,
};
const STATE_DOT: Record<string, string> = { crit: M.crit, warn: M.med, ok: M.ok };

function TimelineChart({ events, sinceHours }: { events: TimelineEvent[]; sinceHours: number }) {
  const now = Date.now();
  const span = sinceHours * 3600_000;
  const W = 300, LH = 26, LABEL_W = 86;
  return (
    <svg viewBox={`0 0 ${W + LABEL_W} ${LANES.length * LH + 6}`} style={{ width: "100%" }}>
      {LANES.map(([key, label], li) => {
        const y = li * LH + LH / 2 + 3;
        return (
          <g key={key}>
            <text x={LABEL_W - 8} y={y + 3} textAnchor="end"
                  style={{ font: `10px ${M.mono}`, fill: M.sub }}>{label}</text>
            <line x1={LABEL_W} y1={y} x2={W + LABEL_W} y2={y} stroke="#eceae2" strokeWidth={1} />
            {events.filter((e) => e.lane === key).map((e, i) => {
              const age = now - new Date(e.t).getTime();
              const x = LABEL_W + Math.max(0, Math.min(1, 1 - age / span)) * W;
              return <circle key={i} cx={x} cy={y} r={3.4}
                             fill={SEV_DOT[e.severity] ?? M.faint} />;
            })}
          </g>
        );
      })}
    </svg>
  );
}

function TrendChart({ c }: { c: SpcChart }) {
  const W = 330, H = 130, PAD = 6;
  const all = [...c.values, c.ucl, c.lcl];
  const lo = Math.min(...all), hi = Math.max(...all);
  const range = hi - lo || 1;
  const y = (v: number) => PAD + (1 - (v - lo) / range) * (H - PAD * 2);
  const x = (i: number) => PAD + (i / Math.max(1, c.values.length - 1)) * (W - PAD * 2);
  const path = c.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
      <line x1={PAD} x2={W - PAD} y1={y(c.ucl)} y2={y(c.ucl)} stroke={M.crit} strokeWidth={1} strokeDasharray="5 4" />
      <line x1={PAD} x2={W - PAD} y1={y(c.lcl)} y2={y(c.lcl)} stroke={M.crit} strokeWidth={1} strokeDasharray="5 4" />
      <text x={PAD + 2} y={y(c.ucl) - 3} style={{ font: `9px ${M.mono}`, fill: M.crit }}>UCL</text>
      <text x={PAD + 2} y={y(c.lcl) + 10} style={{ font: `9px ${M.mono}`, fill: M.crit }}>LCL</text>
      <path d={path} fill="none" stroke="#3a3f52" strokeWidth={1.3} />
      {c.values.map((v, i) => (v > c.ucl || v < c.lcl) && (
        <circle key={i} cx={x(i)} cy={y(v)} r={4} fill="none" stroke={M.crit} strokeWidth={1.6} />
      ))}
    </svg>
  );
}

export function MobileEqpDetail({ id, onBack, onSwitch }: {
  id: string;
  onBack: () => void;
  onSwitch: (id: string) => void;
}) {
  const [eqps, setEqps] = useState<FleetEquipment[]>([]);
  const [modules, setModules] = useState<ModuleCard[]>([]);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [charts, setCharts] = useState<SpcChart[]>([]);
  const [chartIdx, setChartIdx] = useState(0);
  const [tab, setTab] = useState<"health" | "trace">("health");

  const load = useCallback(() => {
    fetch("/api/admin/fleet/equipment?since_hours=24", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.equipment)) setEqps(d.equipment as FleetEquipment[]);
      }).catch(() => { /* ambient */ });
    fetch(`/api/admin/fleet/equipment/${encodeURIComponent(id)}/modules?since_hours=24`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.modules)) setModules(d.modules as ModuleCard[]);
      }).catch(() => { /* ambient */ });
    fetch(`/api/admin/fleet/equipment/${encodeURIComponent(id)}/timeline?since_hours=24`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.events)) setEvents(d.events as TimelineEvent[]);
      }).catch(() => { /* ambient */ });
    fetch(`/api/admin/fleet/equipment/${encodeURIComponent(id)}/spc-trace?limit=100`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.charts)) { setCharts(d.charts as SpcChart[]); setChartIdx(0); }
      }).catch(() => { /* ambient */ });
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const me = useMemo(() => eqps.find((e) => e.id === id), [eqps, id]);
  const chart = charts[chartIdx];
  const scoreTone = (me?.score ?? 100) < 60 ? { fg: M.high, bg: M.highBg }
    : (me?.score ?? 100) < 80 ? { fg: M.med, bg: M.medBg } : { fg: M.ok, bg: M.okBg };

  return (
    <div style={{ padding: "12px 14px 90px", fontFamily: M.sans, color: M.ink }}>
      <button onClick={onBack} style={{
        border: "none", background: "none", padding: 0, fontSize: 12.5, fontWeight: 700,
        color: M.ai, cursor: "pointer",
      }}>‹ 全廠總覽</button>

      <div style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 8 }}>
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: STATE_DOT[(me?.health === "healthy" ? "ok" : me?.health) ?? "ok"] ?? M.ok }} />
        <span style={{ fontFamily: M.mono, fontSize: 22, fontWeight: 800 }}>{id}</span>
        {me && (
          <span style={{
            fontFamily: M.mono, fontSize: 11.5, fontWeight: 700, padding: "2px 9px",
            borderRadius: 12, color: scoreTone.fg, background: scoreTone.bg,
          }}>{me.score}/100</span>
        )}
      </div>
      {me?.note && <div style={{ fontSize: 12, color: M.sub, marginTop: 4 }}>{me.note}</div>}

      {/* 設備切換 chips */}
      <div style={{ display: "flex", gap: 7, overflowX: "auto", margin: "12px -14px 0", padding: "0 14px 4px" }}>
        {eqps.map((e) => (
          <button key={e.id} onClick={() => onSwitch(e.id)} style={{
            flexShrink: 0, border: "none", borderRadius: 10, padding: "7px 13px",
            fontFamily: M.mono, fontSize: 12.5, fontWeight: 700, cursor: "pointer",
            background: e.id === id ? M.ink : "#fff",
            color: e.id === id ? "#fff" : M.sub,
            boxShadow: e.id === id ? "none" : `inset 0 0 0 1px ${M.line}`,
          }}>{e.id}</button>
        ))}
      </div>

      {/* 5 項檢測狀態 */}
      {modules.length > 0 && (
        <div style={{ display: "flex", gap: 8, overflowX: "auto", margin: "10px -14px 0", padding: "0 14px 4px" }}>
          {modules.map((m) => (
            <div key={m.key} style={{ ...cardStyle, padding: "9px 12px", minWidth: 108, flexShrink: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: STATE_DOT[m.state] }} />
                <span style={{ fontFamily: M.mono, fontSize: 11.5, fontWeight: 700 }}>{m.key}</span>
              </div>
              <div style={{ fontFamily: M.mono, fontSize: 13, fontWeight: 700, marginTop: 4 }}>{m.value}</div>
              <div style={{ fontSize: 10, color: M.faint, marginTop: 1 }}>{m.sub}</div>
            </div>
          ))}
        </div>
      )}

      {/* 分頁 */}
      <div style={{
        display: "flex", background: "#eceae0", borderRadius: 12, padding: 3, margin: "14px 0 12px",
      }}>
        {([["health", "健康趨勢"], ["trace", "製程溯源"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            flex: 1, border: "none", borderRadius: 10, padding: "9px 0",
            fontSize: 13, fontWeight: 700, cursor: "pointer",
            background: tab === k ? "#fff" : "transparent",
            color: tab === k ? M.ink : M.sub,
            boxShadow: tab === k ? "0 1px 4px rgba(20,23,60,.12)" : "none",
          }}>{label}</button>
        ))}
      </div>

      {tab === "health" ? (
        <>
          {/* 健康度時間軸 */}
          <div style={{ ...cardStyle, padding: "13px 14px" }}>
            <div style={{ display: "flex", alignItems: "baseline" }}>
              <span style={{ fontSize: 14, fontWeight: 800 }}>健康度時間軸</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontFamily: M.mono, fontSize: 10.5, color: M.faint }}>-24h — now</span>
            </div>
            <div style={{ marginTop: 10 }}>
              <TimelineChart events={events} sinceHours={24} />
            </div>
            <div style={{
              display: "flex", gap: 12, borderTop: `1px solid ${M.line}`,
              paddingTop: 8, marginTop: 8, fontSize: 10.5, color: M.sub, flexWrap: "wrap",
            }}>
              {([["OOC/嚴重", M.crit], ["異常/警告", M.med], ["變更", "#3b6fd4"], ["正常", M.ok]] as const).map(([label, color]) => (
                <span key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: color }} />{label}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 11, color: M.faint, marginTop: 7 }}>共 {events.length} 個事件</div>
          </div>

          {/* SPC 趨勢 */}
          {chart && (
            <div style={{ ...cardStyle, padding: "13px 14px", marginTop: 10 }}>
              <div style={{ display: "flex", alignItems: "center" }}>
                <span style={{ fontSize: 14, fontWeight: 800 }}>趨勢</span>
                <span style={{ flex: 1 }} />
                <select value={chartIdx} onChange={(e) => setChartIdx(Number(e.target.value))} style={{
                  fontFamily: M.mono, fontSize: 12, padding: "4px 8px", borderRadius: 8,
                  border: `1px solid ${M.line}`, background: "#fff", color: M.ink,
                }}>
                  {charts.map((c, i) => <option key={c.chart} value={i}>{c.chart}</option>)}
                </select>
              </div>
              <div style={{ fontFamily: M.mono, fontSize: 11, color: M.sub, margin: "6px 0 2px" }}>
                UCL {chart.ucl} ・ Target {chart.target} ・ LCL {chart.lcl}
              </div>
              <TrendChart c={chart} />
            </div>
          )}
        </>
      ) : (
        <div style={{ ...cardStyle, padding: "20px 16px", textAlign: "center", color: M.sub, fontSize: 13, lineHeight: 1.8 }}>
          製程溯源（LOT lineage／參數對照）資訊量較大，請在桌機版
          <a href={`/dashboard?toolId=${encodeURIComponent(id)}`} style={{ color: M.ai, fontWeight: 700 }}> 設備詳情 </a>
          檢視完整內容。
        </div>
      )}
    </div>
  );
}
