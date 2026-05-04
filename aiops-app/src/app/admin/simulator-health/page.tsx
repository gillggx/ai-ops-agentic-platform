"use client";

import { useEffect, useState } from "react";

interface PerTool {
  tool_id: string;
  events_1h: number;
  lots_per_h: number;
  last_event: string | null;
  lag_sec: number | null;
  ooc_count: number;
  current_lot: string | null;
  current_step: string | null;
  warnings: string[];
}

interface Snapshot {
  now: string;
  uptime_sec: number;
  config: {
    processing_min_sec: number;
    processing_max_sec: number;
    heartbeat_min_sec: number;
    heartbeat_max_sec: number;
    hold_probability: number;
    hold_timeout_sec: number;
    ooc_probability: number;
    total_tools: number;
    total_lots: number;
    recycle_lots: boolean;
    expected_lots_per_hour_per_tool: number;
  };
  health: {
    events_total: number;
    events_1h: number;
    events_10m: number;
    last_event_time: string | null;
    global_lag_sec: number | null;
    active_tools: number;
    configured_tools: number;
    avg_observed_duration_sec: number | null;
  };
  per_tool: PerTool[];
  warnings: { tool_id: string; issue: string }[];
}

const REFRESH_MS = 10_000;

function fmtSec(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  const h = Math.floor(s / 3600);
  return `${h}h ${Math.floor((s - h * 3600) / 60)}m`;
}

function fmtDuration(min: number, max: number): string {
  return `${(min / 60).toFixed(1)}–${(max / 60).toFixed(1)} min`;
}

export default function SimulatorHealthPage() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/admin/simulator-snapshot", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setSnap(body);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  if (!snap && !error) {
    return <div style={{ padding: 16, color: "#6b7280" }}>載入中…</div>;
  }
  if (error && !snap) {
    return (
      <div style={{ padding: 16 }}>
        <h1 style={{ fontSize: 22, marginBottom: 8 }}>💓 Simulator Health</h1>
        <div style={{ padding: 16, background: "#fee2e2", color: "#991b1b", borderRadius: 6 }}>
          錯誤：{error}
        </div>
      </div>
    );
  }
  if (!snap) return null;

  const { config, health, per_tool, warnings } = snap;
  const lagBad = health.global_lag_sec != null && health.global_lag_sec > 60;
  const minThroughput = config.expected_lots_per_hour_per_tool * 0.5;

  return (
    <div style={{ maxWidth: 1280 }}>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>💓 Simulator Health</h1>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          {loading ? "refreshing…" : `auto-refresh ${REFRESH_MS / 1000}s · uptime ${fmtSec(snap.uptime_sec)}`}
        </div>
      </header>

      {/* Top warnings strip */}
      {warnings.length > 0 && (
        <section style={{ marginBottom: 16, background: "#fef3c7", border: "1px solid #fcd34d", borderRadius: 6, padding: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 6, color: "#92400e" }}>
            ⚠ {warnings.length} warning(s)
          </div>
          <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: "#7c2d12" }}>
            {warnings.slice(0, 8).map((w, i) => (
              <li key={i}>
                <strong>{w.tool_id}</strong>: {w.issue}
              </li>
            ))}
            {warnings.length > 8 && <li>… and {warnings.length - 8} more</li>}
          </ul>
        </section>
      )}

      {/* Health cards */}
      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginBottom: 16 }}>
        <Card label="Events (last 1h)" value={String(health.events_1h)} sub={`${health.events_10m} in last 10m`} />
        <Card
          label="Active tools"
          value={`${health.active_tools} / ${health.configured_tools}`}
          sub={health.active_tools < health.configured_tools ? "some idle/stuck" : "all healthy"}
          tone={health.active_tools < health.configured_tools ? "warn" : "ok"}
        />
        <Card
          label="Global lag"
          value={fmtSec(health.global_lag_sec)}
          sub={lagBad ? "simulator may be down" : "fresh"}
          tone={lagBad ? "bad" : "ok"}
        />
        <Card
          label="Avg duration (observed)"
          value={health.avg_observed_duration_sec ? `${(health.avg_observed_duration_sec / 60).toFixed(1)} min` : "—"}
          sub={`expected ${fmtDuration(config.processing_min_sec, config.processing_max_sec)}`}
        />
        <Card label="Total events" value={String(health.events_total)} sub={`recycle: ${config.recycle_lots ? "on" : "off"}`} />
      </section>

      {/* Config readout */}
      <section style={{ marginBottom: 16, background: "#f9fafb", padding: 12, borderRadius: 6, fontSize: 13 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Config (這次 simulator 啟動時的契約)</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, color: "#374151" }}>
          <div>Process duration: <code>{fmtDuration(config.processing_min_sec, config.processing_max_sec)}</code></div>
          <div>Expected lots/h/tool: <code>{config.expected_lots_per_hour_per_tool}</code></div>
          <div>HOLD probability: <code>{(config.hold_probability * 100).toFixed(1)}%</code></div>
          <div>HOLD timeout: <code>{fmtSec(config.hold_timeout_sec)}</code></div>
          <div>OOC probability: <code>{(config.ooc_probability * 100).toFixed(1)}%</code></div>
          <div>Tools: <code>{config.total_tools}</code> · Lots: <code>{config.total_lots}</code></div>
        </div>
      </section>

      {/* Per-tool table */}
      <section>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Per-tool</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", background: "#f9fafb" }}>
              <Th>Tool</Th>
              <Th align="right">Lots/h</Th>
              <Th align="right">Events/h</Th>
              <Th align="right">OOC/h</Th>
              <Th align="right">Lag</Th>
              <Th>Current Lot</Th>
              <Th>Step</Th>
              <Th>Warnings</Th>
            </tr>
          </thead>
          <tbody>
            {per_tool.map((t) => {
              const lagBad = t.lag_sec != null && t.lag_sec > config.processing_max_sec * 2;
              const throughputBad = t.lots_per_h < minThroughput;
              const rowBg = t.warnings.length > 0 ? "#fef2f2" : undefined;
              return (
                <tr key={t.tool_id} style={{ borderBottom: "1px solid #f3f4f6", background: rowBg }}>
                  <Td><strong>{t.tool_id}</strong></Td>
                  <Td align="right" tone={throughputBad ? "bad" : undefined}>{t.lots_per_h}</Td>
                  <Td align="right">{t.events_1h}</Td>
                  <Td align="right">{t.ooc_count}</Td>
                  <Td align="right" tone={lagBad ? "bad" : undefined}>{fmtSec(t.lag_sec)}</Td>
                  <Td mono>{t.current_lot ?? "—"}</Td>
                  <Td mono>{t.current_step ?? "—"}</Td>
                  <Td>
                    {t.warnings.length === 0 ? (
                      <span style={{ color: "#10b981" }}>✓</span>
                    ) : (
                      <span style={{ color: "#dc2626" }}>{t.warnings.join("; ")}</span>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <footer style={{ marginTop: 24, fontSize: 11, color: "#9ca3af" }}>
        snapshot @ {snap.now} · refresh every {REFRESH_MS / 1000}s
      </footer>
    </div>
  );
}

function Card({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "ok" | "warn" | "bad" }) {
  const color = tone === "bad" ? "#b91c1c" : tone === "warn" ? "#92400e" : "#1f2937";
  const bg = tone === "bad" ? "#fee2e2" : tone === "warn" ? "#fef3c7" : "#fff";
  return (
    <div style={{ background: bg, border: "1px solid #e5e7eb", borderRadius: 6, padding: "10px 12px" }}>
      <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Th({ children, align }: { children: React.ReactNode; align?: "right" }) {
  return (
    <th style={{ textAlign: align ?? "left", padding: "6px 10px", fontWeight: 600, color: "#374151" }}>
      {children}
    </th>
  );
}

function Td({ children, align, mono, tone }: { children: React.ReactNode; align?: "right"; mono?: boolean; tone?: "bad" }) {
  return (
    <td style={{
      textAlign: align ?? "left",
      padding: "6px 10px",
      fontFamily: mono ? "var(--font-mono)" : undefined,
      color: tone === "bad" ? "#b91c1c" : "#1f2937",
      fontWeight: tone === "bad" ? 600 : undefined,
    }}>
      {children}
    </td>
  );
}
