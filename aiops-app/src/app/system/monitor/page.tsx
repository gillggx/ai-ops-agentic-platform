"use client";

import { useCallback, useEffect, useState } from "react";

// 2026-05-24: shape updated to match Java backend rewrite (commit 046f85e).
// Python event_poller is gone — Java scheduler unit owns cron + event dispatch.
// SkillRunner in-memory alarm counters surface here instead.
interface MonitorData {
  timestamp: string;
  services: Record<string, { status: string; port?: number; data?: Record<string, unknown>; error?: string }>;
  background_tasks: {
    skill_runner: {
      alarms_emitted: number;
      alarms_dedup_suppressed: number;
      last_emit_at: string | null;
      last_skill: string | null;
      last_alarm_id: number | null;
    };
    cron_scheduler: {
      status: string;     // "JAVA" — handled by aiops-java-scheduler unit
      note?: string;
    };
  };
  db_stats: Record<string, number>;
  build_info?: { service?: string; backend?: string };
}

function StatusDot({ up }: { up: boolean }) {
  return (
    <span style={{
      display: "inline-block", width: 10, height: 10, borderRadius: "50%",
      background: up ? "#38a169" : "#e53e3e", marginRight: 8, flexShrink: 0,
    }} />
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function SystemMonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/monitor", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  if (loading) return <div style={{ padding: 48, textAlign: "center", color: "#718096" }}>Loading...</div>;
  if (error) return <div style={{ padding: 48, color: "#e53e3e" }}>Error: {error}</div>;
  if (!data) return null;

  const skillRunner = data.background_tasks.skill_runner;
  const scheduler = data.background_tasks.cron_scheduler;

  const cardStyle: React.CSSProperties = {
    background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0",
    padding: "16px 20px", marginBottom: 16,
  };
  const titleStyle: React.CSSProperties = {
    fontSize: 13, fontWeight: 700, color: "#4a5568", marginBottom: 12,
    textTransform: "uppercase", letterSpacing: "0.3px",
  };

  return (
    <div style={{ padding: "16px 20px", maxWidth: 900 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#1a202c" }}>System Monitor</h1>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#a0aec0" }}>
          Auto-refresh every 10s | Last update: {timeAgo(data.timestamp)}
        </p>
      </div>

      {/* Services */}
      <div style={cardStyle}>
        <div style={titleStyle}>Services</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
          {Object.entries(data.services).map(([name, svc]) => (
            <div key={name} style={{
              display: "flex", alignItems: "center", padding: "10px 14px",
              background: svc.status === "UP" ? "#f0fff4" : "#fff5f5",
              borderRadius: 8, border: `1px solid ${svc.status === "UP" ? "#c6f6d5" : "#fed7d7"}`,
            }}>
              <StatusDot up={svc.status === "UP"} />
              <div>
                <div style={{ fontWeight: 600, fontSize: 13, color: "#1a202c" }}>{name}</div>
                <div style={{ fontSize: 11, color: "#718096" }}>
                  {svc.port ? `port ${svc.port}` : ""} {svc.status}
                  {svc.error && <span style={{ color: "#e53e3e" }}> — {svc.error}</span>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Skill Runner (alarm-emit activity) */}
      <div style={cardStyle}>
        <div style={titleStyle}>Skill Runner — Alarm Emit</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          {[
            { label: "Alarms Emitted", value: skillRunner.alarms_emitted ?? 0 },
            { label: "Dedup Suppressed", value: skillRunner.alarms_dedup_suppressed ?? 0 },
            { label: "Last Emit", value: timeAgo(skillRunner.last_emit_at) },
            { label: "Last Alarm #", value: skillRunner.last_alarm_id ?? "—" },
          ].map(({ label, value }) => (
            <div key={label} style={{ padding: "8px 10px", background: "#f7fafc", borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: "#a0aec0", fontWeight: 600, textTransform: "uppercase" }}>{label}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#2d3748", marginTop: 2 }}>{value}</div>
            </div>
          ))}
        </div>
        {skillRunner.last_skill && (
          <div style={{ marginTop: 10, padding: "8px 10px", background: "#edf2f7", borderRadius: 6, fontSize: 12, color: "#4a5568" }}>
            Last skill: <span style={{ fontFamily: "monospace" }}>{skillRunner.last_skill}</span>
          </div>
        )}
        <div style={{ marginTop: 10, fontSize: 11, color: "#a0aec0" }}>
          In-memory counters; reset on JVM restart. Persistent metrics: query <code>alarms</code> / <code>skill_runs</code> tables directly.
        </div>
      </div>

      {/* Cron Scheduler */}
      <div style={cardStyle}>
        <div style={titleStyle}>Cron Scheduler</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <StatusDot up={scheduler.status === "JAVA" || scheduler.status === "RUNNING"} />
          <span style={{ fontWeight: 600, fontSize: 13 }}>{scheduler.status}</span>
        </div>
        {scheduler.note && (
          <div style={{ fontSize: 11, color: "#718096", marginLeft: 18 }}>{scheduler.note}</div>
        )}
      </div>

      {/* DB Stats */}
      <div style={cardStyle}>
        <div style={titleStyle}>Database</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          {Object.entries(data.db_stats).map(([table, count]) => (
            <div key={table} style={{ padding: "8px 10px", background: "#f7fafc", borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: "#a0aec0", fontWeight: 600 }}>{table.replace(/_/g, " ")}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#2d3748", marginTop: 2 }}>{count}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
