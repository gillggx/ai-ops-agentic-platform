"use client";

import { useEffect, useState, useCallback } from "react";
import { RenderMiddleware, type SkillFindings, type OutputSchemaField, type ChartDSL } from "./SkillOutputRenderer";

type DiagnosticResult = {
  log_id: number;
  skill_id: number | null;
  skill_name: string;
  status: string;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  charts: ChartDSL[] | null;
};

// Pipeline-mode data view (one block_data_view node output).
type DataView = {
  title: string | null;
  description: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
};

type AlertEmission = {
  severity?: string;
  title?: string;
  message?: string;
  evidence_count?: number;
  emitted_at?: string;
} | null;

type Alarm = {
  id: number;
  skill_id: number;
  trigger_event: string;
  equipment_id: string;
  lot_id: string;
  step: string | null;
  event_time: string | null;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  title: string;
  summary: string | null;
  status: "active" | "acknowledged" | "resolved";
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  execution_log_id: number | null;
  diagnostic_log_id: number | null;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  charts?: ChartDSL[] | null;
  // New: full list of DR results (one entry per bound Diagnostic Rule)
  diagnostic_results?: DiagnosticResult[];
  // Legacy single-DR fields (back-compat only)
  diagnostic_findings: SkillFindings | null;
  diagnostic_output_schema: OutputSchemaField[] | null;
  // Pipeline-mode views (block_data_view outputs from the execution / auto_check run)
  trigger_data_views?: DataView[];
  diagnostic_data_views?: DataView[];
  diagnostic_charts?: ChartDSL[];
  diagnostic_alert?: AlertEmission;
};

// ── Severity config ────────────────────────────────────────────────────────────

const SEV: Record<string, { bg: string; color: string; dot: string; label: string }> = {
  CRITICAL: { bg: "#fef2f2", color: "#dc2626", dot: "#dc2626", label: "CRITICAL" },
  HIGH:     { bg: "#fff7ed", color: "#ea580c", dot: "#ea580c", label: "HIGH" },
  MEDIUM:   { bg: "#fefce8", color: "#ca8a04", dot: "#ca8a04", label: "MEDIUM" },
  LOW:      { bg: "#f0fdf4", color: "#16a34a", dot: "#16a34a", label: "LOW" },
};

// ── Helpers ────────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)    return `${Math.floor(diff)}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function parseSummary(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SeverityBadge({ sev }: { sev: string }) {
  const cfg = SEV[sev] ?? SEV.MEDIUM;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 12,
      background: cfg.bg, color: cfg.color,
      fontSize: 11, fontWeight: 700, letterSpacing: "0.3px",
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: cfg.dot, flexShrink: 0 }} />
      {cfg.label}
    </span>
  );
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    active:       { bg: "#fff5f5", color: "#c53030", label: "OPEN" },
    acknowledged: { bg: "#ebf8ff", color: "#2b6cb0", label: "已認領" },
    resolved:     { bg: "#f0fff4", color: "#276749", label: "已解決" },
  };
  const cfg = map[status] ?? map.active;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 10,
      background: cfg.bg, color: cfg.color,
      fontSize: 11, fontWeight: 600,
    }}>
      {cfg.label}
    </span>
  );
}

// ── Alarm Detail Modal ────────────────────────────────────────────────────────

function DataViewTable({ dv }: { dv: DataView }) {
  // Compact, monospaced table — 8 cols max, 10 rows max in alarm modal.
  const cols = (dv.columns || []).slice(0, 8);
  const rows = (dv.rows || []).slice(0, 10);
  if (cols.length === 0 && rows.length === 0) {
    return <div style={{ fontSize: 12, color: "#a0aec0" }}>無資料</div>;
  }
  return (
    <div style={{
      border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden",
      background: "#fff", marginBottom: 12,
    }}>
      {dv.title && (
        <div style={{
          padding: "8px 12px", background: "#f7fafc",
          borderBottom: "1px solid #e2e8f0",
          fontSize: 12, fontWeight: 700, color: "#2d3748",
        }}>
          📋 {dv.title}
          {dv.total_rows > rows.length && (
            <span style={{ marginLeft: 8, fontSize: 10, color: "#a0aec0", fontWeight: 400 }}>
              ({rows.length}/{dv.total_rows} 列)
            </span>
          )}
        </div>
      )}
      {dv.description && (
        <div style={{ padding: "6px 12px", fontSize: 11, color: "#718096", borderBottom: "1px solid #f0f4f8" }}>
          {dv.description}
        </div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "monospace" }}>
          <thead>
            <tr style={{ background: "#f7fafc" }}>
              {cols.map((c) => (
                <th key={c} style={{
                  padding: "6px 8px", textAlign: "left", color: "#4a5568",
                  borderBottom: "1px solid #e2e8f0", fontWeight: 600, whiteSpace: "nowrap",
                }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} style={{ borderBottom: "1px solid #f0f4f8" }}>
                {cols.map((c) => {
                  const v = row[c];
                  const isOOC = c.endsWith("_is_ooc") && v === true;
                  const isTriggered = c === "triggered_row" && v === true;
                  const isOOCStatus = c === "spc_status" && v === "OOC";
                  const highlight = isOOC || isTriggered || isOOCStatus;
                  return (
                    <td key={c} style={{
                      padding: "6px 8px", whiteSpace: "nowrap",
                      color: highlight ? "#dc2626" : "#2d3748",
                      fontWeight: highlight ? 700 : 400,
                      background: highlight ? "#fef2f2" : "transparent",
                    }}>
                      {v === null || v === undefined ? "—"
                        : typeof v === "object" ? JSON.stringify(v)
                        : typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(3))
                        : String(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AlarmDetailModal({ alarm, onClose }: { alarm: Alarm; onClose: () => void }) {
  const [tab, setTab] = useState<"trigger" | "diagnostic">("trigger");

  const triggerDvs = alarm.trigger_data_views ?? [];
  const diagnosticDvs = alarm.diagnostic_data_views ?? [];
  const diagnosticCharts = alarm.diagnostic_charts ?? [];
  const diagnosticAlert = alarm.diagnostic_alert ?? null;

  const hasApFindings = alarm.findings && Object.keys(alarm.findings).length > 0;
  const diagnosticResults = alarm.diagnostic_results ?? [];
  // Legacy fallback: if backend didn't provide diagnostic_results but has the old single-field, synthesise one entry
  const drList: DiagnosticResult[] = diagnosticResults.length > 0
    ? diagnosticResults
    : (alarm.diagnostic_findings ? [{
        log_id: alarm.diagnostic_log_id ?? 0,
        skill_id: null,
        skill_name: "Diagnostic Rule",
        status: "success",
        findings: alarm.diagnostic_findings,
        output_schema: alarm.diagnostic_output_schema,
        charts: null,
      }] : []);
  const hasDrFindings = drList.length > 0;
  const parsed = parseSummary(alarm.summary);
  const sev = SEV[alarm.severity] ?? SEV.MEDIUM;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 12,
          width: "min(720px, 90vw)", maxHeight: "85vh",
          display: "flex", flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "16px 20px", borderBottom: "1px solid #e2e8f0",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{
              width: 28, height: 28, borderRadius: 6, background: sev.bg,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 14,
            }}>🚨</span>
            <div>
              <div style={{ fontWeight: 700, fontSize: 15, color: "#1a202c" }}>
                AI 診斷報告 | {alarm.equipment_id} - {alarm.title}
              </div>
              <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 1 }}>
                {alarm.trigger_event} · {timeAgo(alarm.created_at)}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none", border: "none", fontSize: 20, color: "#a0aec0",
              cursor: "pointer", padding: "4px 8px", lineHeight: 1,
            }}
          >✕</button>
        </div>

        {/* Tabs */}
        <div style={{
          display: "flex", gap: 0, borderBottom: "1px solid #e2e8f0",
          padding: "0 20px",
        }}>
          <button
            onClick={() => setTab("trigger")}
            style={{
              padding: "10px 16px", border: "none", cursor: "pointer",
              borderBottom: tab === "trigger" ? "2px solid #2b6cb0" : "2px solid transparent",
              background: "transparent",
              color: tab === "trigger" ? "#2b6cb0" : "#718096",
              fontWeight: tab === "trigger" ? 700 : 400,
              fontSize: 13, marginBottom: -1,
            }}
          >1. 觸發事件 (Trigger Event)</button>
          <button
            onClick={() => setTab("diagnostic")}
            style={{
              padding: "10px 16px", border: "none", cursor: "pointer",
              borderBottom: tab === "diagnostic" ? "2px solid #2b6cb0" : "2px solid transparent",
              background: "transparent",
              color: tab === "diagnostic" ? "#2b6cb0" : "#718096",
              fontWeight: tab === "diagnostic" ? 700 : 400,
              fontSize: 13, marginBottom: -1,
            }}
          >2. 診斷分析 (Diagnostic Analysis)</button>
        </div>

        {/* Tab content */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px" }}>
          {tab === "trigger" && (
            <div>
              {/* Trigger banner */}
              <div style={{
                background: alarm.findings?.condition_met ? "#fef2f2" : "#f0fdf4",
                border: `1px solid ${alarm.findings?.condition_met ? "#fca5a5" : "#86efac"}`,
                borderRadius: 8, padding: "14px 16px", marginBottom: 16,
              }}>
                <div style={{
                  fontSize: 12, fontWeight: 700, marginBottom: 4,
                  color: alarm.findings?.condition_met ? "#dc2626" : "#16a34a",
                }}>
                  {alarm.findings?.condition_met ? "🔴 觸發原因 (AUTO-PATROL)" : "🟢 觸發原因 (AUTO-PATROL)"}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#1a202c" }}>
                  {alarm.findings?.condition_met ? "條件達成 — 將觸發警報" : "條件未達成"}
                </div>
                {alarm.findings?.summary && (
                  <div style={{
                    marginTop: 8, padding: "8px 12px", borderRadius: 6,
                    background: alarm.findings.condition_met ? "#fee2e2" : "#dcfce7",
                    fontSize: 12, color: "#4a5568", fontFamily: "monospace",
                  }}>
                    {alarm.findings.summary}
                  </div>
                )}
              </div>

              {/* Pipeline-mode trigger evidence (block_data_view rows from the patrol pipeline) */}
              {triggerDvs.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700, color: "#4a5568",
                    textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8,
                  }}>
                    觸發證據（patrol pipeline 回傳）
                  </div>
                  {triggerDvs.map((dv, i) => <DataViewTable key={i} dv={dv} />)}
                </div>
              )}

              {/* Rendered findings — legacy DR / skill format */}
              {hasApFindings ? (
                <RenderMiddleware findings={alarm.findings!} outputSchema={alarm.output_schema ?? []} charts={alarm.charts ?? null} />
              ) : parsed && Object.keys(parsed).length > 0 ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {Object.entries(parsed).map(([k, v]) => (
                    <div key={k} style={{
                      background: "#f7fafc", border: "1px solid #e2e8f0", borderRadius: 6,
                      padding: "6px 12px", fontSize: 12,
                    }}>
                      <span style={{ color: "#718096" }}>{k}: </span>
                      <span style={{ fontWeight: 600, color: "#2d3748" }}>
                        {typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : triggerDvs.length === 0 ? (
                <div style={{ fontSize: 12, color: "#a0aec0" }}>{alarm.summary || "無觸發資料"}</div>
              ) : null}
            </div>
          )}

          {tab === "diagnostic" && (
            <div>
              {/* Pipeline-mode diagnostic output (auto_check pb_pipeline_runs result_summary) */}
              {(diagnosticDvs.length > 0 || diagnosticCharts.length > 0 || diagnosticAlert) && (
                <div style={{
                  border: "1px solid #e2e8f0", borderRadius: 10,
                  padding: "14px 16px", marginBottom: 16, background: "#fff",
                }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700, color: "#4a5568",
                    textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8,
                  }}>
                    Auto-Check 診斷 (pipeline run)
                  </div>
                  {diagnosticAlert?.title && (
                    <div style={{
                      background: "#fef2f2", border: "1px solid #fca5a5",
                      borderRadius: 8, padding: "10px 14px", marginBottom: 12,
                    }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#dc2626", marginBottom: 4 }}>
                        ⚠ {diagnosticAlert.title}
                      </div>
                      {diagnosticAlert.message && (
                        <div style={{ fontSize: 12, color: "#4a5568" }}>{diagnosticAlert.message}</div>
                      )}
                    </div>
                  )}
                  {diagnosticDvs.map((dv, i) => <DataViewTable key={i} dv={dv} />)}
                  {diagnosticCharts.length > 0 && (
                    <div style={{ fontSize: 11, color: "#718096" }}>
                      {diagnosticCharts.length} 張 chart（請至完整 Pipeline Run 頁面檢視）
                    </div>
                  )}
                </div>
              )}

              {hasDrFindings ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                  {drList.map((dr, idx) => {
                    const metaColor = dr.findings?.condition_met ? "#dc2626" : "#16a34a";
                    const bannerBg = dr.findings?.condition_met ? "#fef2f2" : "#f0fdf4";
                    const bannerBorder = dr.findings?.condition_met ? "#fca5a5" : "#86efac";
                    return (
                      <div key={dr.log_id || idx} style={{
                        border: "1px solid #e2e8f0", borderRadius: 10, padding: 0, overflow: "hidden",
                      }}>
                        {/* DR header strip */}
                        <div style={{
                          padding: "10px 14px", background: "#f7fafc",
                          borderBottom: "1px solid #e2e8f0",
                          display: "flex", alignItems: "center", gap: 8,
                        }}>
                          <span style={{
                            padding: "2px 8px", borderRadius: 4, background: "#2d3748", color: "#fff",
                            fontSize: 10, fontWeight: 700, letterSpacing: "0.3px",
                          }}>DR {idx + 1}/{drList.length}</span>
                          <span style={{ fontSize: 13, fontWeight: 600, color: "#1a202c" }}>
                            {dr.skill_name || `Rule #${dr.skill_id}`}
                          </span>
                          {dr.skill_id && (
                            <a href={`/admin/skills?edit=${dr.skill_id}`} target="_blank" rel="noreferrer"
                              style={{
                                marginLeft: "auto", fontSize: 11, color: "#2b6cb0", textDecoration: "none",
                              }}
                            >編輯 ↗</a>
                          )}
                        </div>

                        {/* Diagnostic banner */}
                        <div style={{ padding: "14px 16px" }}>
                          <div style={{
                            background: bannerBg, border: `1px solid ${bannerBorder}`,
                            borderRadius: 8, padding: "14px 16px", marginBottom: 12,
                          }}>
                            <div style={{
                              fontSize: 12, fontWeight: 700, marginBottom: 4, color: metaColor,
                            }}>
                              {dr.findings?.condition_met
                                ? "🔴 深度診斷結果 (DIAGNOSTIC RULE)"
                                : "🟢 深度診斷結果 (DIAGNOSTIC RULE)"}
                            </div>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "#1a202c" }}>
                              {dr.findings?.condition_met ? "條件達成 — 需要處置" : "條件未達成 — 不需觸發警報"}
                            </div>
                            {dr.findings?.summary && (
                              <div style={{
                                marginTop: 8, padding: "8px 12px", borderRadius: 6,
                                background: dr.findings.condition_met ? "#fee2e2" : "#dcfce7",
                                fontSize: 12, color: "#4a5568",
                              }}>
                                {dr.findings.summary}
                              </div>
                            )}
                          </div>

                          {dr.findings && (
                            <RenderMiddleware
                              findings={dr.findings}
                              outputSchema={dr.output_schema ?? []}
                              charts={dr.charts ?? null}
                            />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (diagnosticDvs.length > 0 || diagnosticCharts.length > 0 || diagnosticAlert) ? (
                null
              ) : alarm.diagnostic_log_id ? (
                <div style={{ padding: 32, textAlign: "center", color: "#a0aec0" }}>
                  <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
                  <div style={{ fontSize: 13 }}>診斷規則已觸發，等待結果...</div>
                </div>
              ) : (
                <div style={{ padding: 32, textAlign: "center", color: "#a0aec0" }}>
                  <div style={{ fontSize: 24, marginBottom: 8 }}>📋</div>
                  <div style={{ fontSize: 13 }}>尚無診斷規則結果</div>
                  <a
                    href="/admin/skills"
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      display: "inline-block", marginTop: 12,
                      padding: "6px 14px", borderRadius: 6,
                      background: "#ebf4ff", color: "#2b6cb0",
                      fontSize: 12, fontWeight: 600, textDecoration: "none",
                    }}
                  >🔬 前往 Diagnostic Rules</a>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── AlarmRow ───────────────────────────────────────────────────────────────────

function AlarmRow({
  alarm,
  onSelect,
  onAck,
  onResolve,
}: {
  alarm: Alarm;
  onSelect: () => void;
  onAck: (id: number) => void;
  onResolve: (id: number) => void;
}) {
  return (
    <div style={{ borderBottom: "1px solid #e2e8f0" }}>
      <div
        onClick={onSelect}
        style={{
          display: "grid",
          gridTemplateColumns: "90px 1fr 100px 80px 90px 140px",
          alignItems: "center",
          gap: 8,
          padding: "10px 16px",
          cursor: "pointer",
          background: "#fff",
          transition: "background 0.1s",
        }}
        onMouseEnter={e => { e.currentTarget.style.background = "#f7fafc"; }}
        onMouseLeave={e => { e.currentTarget.style.background = "#fff"; }}
      >
        <SeverityBadge sev={alarm.severity} />

        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: "#1a202c", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {alarm.title}
          </div>
          <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 1 }}>{alarm.trigger_event}</div>
        </div>

        <div style={{ fontSize: 12, color: "#4a5568", fontWeight: 500 }}>
          {alarm.equipment_id || "—"}
        </div>

        <div style={{ fontSize: 11, color: "#a0aec0" }}>{timeAgo(alarm.created_at)}</div>

        <StatusChip status={alarm.status} />

        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }} onClick={e => e.stopPropagation()}>
          {alarm.status === "active" && (
            <button
              onClick={() => onAck(alarm.id)}
              style={{
                padding: "3px 10px", borderRadius: 5, border: "1px solid #bee3f8",
                background: "#ebf8ff", color: "#2b6cb0",
                fontSize: 11, fontWeight: 600, cursor: "pointer",
              }}
            >認領</button>
          )}
          {alarm.status !== "resolved" && (
            <button
              onClick={() => onResolve(alarm.id)}
              style={{
                padding: "3px 10px", borderRadius: 5, border: "1px solid #c6f6d5",
                background: "#f0fff4", color: "#276749",
                fontSize: 11, fontWeight: 600, cursor: "pointer",
              }}
            >解決</button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onSelect(); }}
            style={{
              padding: "3px 10px", borderRadius: 5, border: "1px solid #e2e8f0",
              background: "#f7fafc", color: "#4a5568",
              fontSize: 11, fontWeight: 600, cursor: "pointer",
            }}
          >AI診斷</button>
        </div>
      </div>
    </div>
  );
}

// ── Main AlarmCenter ───────────────────────────────────────────────────────────

const STATUS_TABS = [
  { key: "active",       label: "OPEN" },
  { key: "acknowledged", label: "已認領" },
  { key: "all",          label: "全部" },
];

const SEV_OPTS = ["全部", "CRITICAL", "HIGH", "MEDIUM", "LOW"];

export function AlarmCenter() {
  const [alarms, setAlarms]             = useState<Alarm[]>([]);
  const [loading, setLoading]           = useState(true);
  const [statusTab, setStatusTab]       = useState<string>("all");
  const [sevFilter, setSevFilter]       = useState("全部");
  const [eqFilter, setEqFilter]         = useState("");
  const [selectedAlarm, setSelectedAlarm] = useState<Alarm | null>(null);
  const [counts, setCounts]             = useState<Record<string, number>>({ active: 0, acknowledged: 0 });

  const fetchAlarms = useCallback(async () => {
    const params = new URLSearchParams({ status: statusTab, limit: "100" });
    if (sevFilter !== "全部") params.set("severity", sevFilter);
    if (eqFilter.trim()) params.set("equipment_id", eqFilter.trim());

    const res = await fetch(`/api/admin/alarms?${params}`);
    if (!res.ok) return;
    const data: Alarm[] = await res.json();
    setAlarms(data);
    setLoading(false);
  }, [statusTab, sevFilter, eqFilter]);

  // Fetch counts for tab badges
  const fetchCounts = useCallback(async () => {
    const [activeRes, ackedRes] = await Promise.all([
      fetch("/api/admin/alarms?status=active&limit=1"),
      fetch("/api/admin/alarms?status=acknowledged&limit=1"),
    ]);
    // counts are approximate via stats endpoint
    const statsRes = await fetch("/api/admin/alarms/stats");
    if (statsRes.ok) {
      const stats = await statsRes.json();
      setCounts({
        active: stats.total_active ?? 0,
        acknowledged: 0, // not in stats, just show total_active
      });
    }
  }, []);

  useEffect(() => { fetchAlarms(); }, [fetchAlarms]);
  useEffect(() => { fetchCounts(); }, [fetchCounts]);

  // Poll every 15s
  useEffect(() => {
    const id = setInterval(() => { fetchAlarms(); fetchCounts(); }, 15000);
    return () => clearInterval(id);
  }, [fetchAlarms, fetchCounts]);

  async function handleAck(id: number) {
    await fetch(`/api/admin/alarms/${id}/acknowledge`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledged_by: "operator" }),
    });
    fetchAlarms();
    fetchCounts();
  }

  async function handleResolve(id: number) {
    await fetch(`/api/admin/alarms/${id}/resolve`, { method: "PATCH" });
    fetchAlarms();
    fetchCounts();
  }

  // Summary bar counts by severity (from current list)
  const critCount = alarms.filter(a => a.severity === "CRITICAL").length;
  const highCount = alarms.filter(a => a.severity === "HIGH").length;
  const medCount  = alarms.filter(a => a.severity === "MEDIUM").length;
  const lowCount  = alarms.filter(a => a.severity === "LOW").length;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1a202c" }}>告警中心</h2>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#a0aec0" }}>每 15 秒自動更新 · 點擊列可展開診斷結果</p>
        </div>

        {/* Severity summary pills */}
        <div style={{ display: "flex", gap: 8 }}>
          {(
            [
              { key: "CRITICAL", count: critCount },
              { key: "HIGH",     count: highCount },
              { key: "MEDIUM",   count: medCount  },
              { key: "LOW",      count: lowCount  },
            ] as { key: keyof typeof SEV; count: number }[]
          ).map(({ key, count }) => {
            const { bg, color, label } = SEV[key];
            return (
            <div key={label} style={{
              padding: "4px 12px", borderRadius: 16,
              background: count > 0 ? bg : "#f7fafc",
              color: count > 0 ? color : "#a0aec0",
              fontSize: 12, fontWeight: 700,
              border: `1px solid ${count > 0 ? color + "33" : "#e2e8f0"}`,
            }}>
              {label}: {count}
            </div>
            );
          })}
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", marginBottom: 12, gap: 12 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <select
            value={sevFilter}
            onChange={e => { setSevFilter(e.target.value); }}
            style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #e2e8f0", fontSize: 12, color: "#4a5568" }}
          >
            {SEV_OPTS.map(s => <option key={s}>{s}</option>)}
          </select>
          <input
            placeholder="設備 ID..."
            value={eqFilter}
            onChange={e => setEqFilter(e.target.value)}
            style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #e2e8f0", fontSize: 12, width: 120, color: "#4a5568" }}
          />
        </div>
      </div>

      {/* Table header */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "90px 1fr 100px 80px 90px 140px",
        gap: 8,
        padding: "6px 16px",
        background: "#f7fafc",
        borderRadius: "8px 8px 0 0",
        border: "1px solid #e2e8f0",
        borderBottom: "none",
        fontSize: 11, fontWeight: 600, color: "#718096", textTransform: "uppercase", letterSpacing: "0.4px",
      }}>
        <span>嚴重度</span>
        <span>標題</span>
        <span>設備</span>
        <span>時間</span>
        <span>狀態</span>
        <span style={{ textAlign: "right" }}>操作</span>
      </div>

      {/* Alarm list */}
      <div style={{ border: "1px solid #e2e8f0", borderRadius: "0 0 8px 8px", background: "#fff", overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>載入中...</div>
        ) : alarms.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <div style={{ fontSize: 14, color: "#4a5568", fontWeight: 600 }}>
              {statusTab === "active" ? "目前沒有未處理的告警" : "沒有符合條件的告警"}
            </div>
            <div style={{ fontSize: 12, color: "#a0aec0", marginTop: 4 }}>
              Auto-Patrol 持續監控中...
            </div>
          </div>
        ) : (
          alarms.map(alarm => (
            <AlarmRow
              key={alarm.id}
              alarm={alarm}
              onSelect={() => setSelectedAlarm(alarm)}
              onAck={handleAck}
              onResolve={handleResolve}
            />
          ))
        )}
      </div>

      {alarms.length > 0 && (
        <div style={{ textAlign: "right", fontSize: 11, color: "#a0aec0", marginTop: 6 }}>
          共 {alarms.length} 筆
        </div>
      )}

      {/* Detail modal */}
      {selectedAlarm && (
        <AlarmDetailModal alarm={selectedAlarm} onClose={() => setSelectedAlarm(null)} />
      )}
    </div>
  );
}
