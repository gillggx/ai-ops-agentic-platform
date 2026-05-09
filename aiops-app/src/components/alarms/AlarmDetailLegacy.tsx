"use client";

/**
 * Per-alarm detail UI — extracted from app/alarms/page.tsx so the new
 * cluster-first shell can compose it inside ClusterDetailPanel. The
 * tab logic, multi-run rendering, and DR accordions are preserved
 * verbatim; only the surrounding layout chrome is gone.
 */

import { useEffect, useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import {
  RenderMiddleware, ChartListRenderer,
  type SkillFindings, type OutputSchemaField, type ChartDSL,
} from "@/components/operations/SkillOutputRenderer";
import { DRErrorBoundary } from "@/components/alarms/DRErrorBoundary";

// ── Types (mirror of app/alarms/page.tsx originals) ──────────

export type DiagnosticResult = {
  log_id: number;
  skill_id: number | null;
  skill_name: string;
  status: string;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  charts: ChartDSL[] | null;
};

export type DataView = {
  title: string | null;
  description: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
};

export type AlertEmission = {
  severity?: string;
  title?: string;
  message?: string;
  evidence_count?: number;
  emitted_at?: string;
} | null;

export type AutoCheckRun = {
  run_id: number;
  pipeline_id: number;
  pipeline_name: string | null;
  status: string;
  data_views: DataView[];
  charts: ChartDSL[];
  alert: AlertEmission;
};

export type Alarm = {
  id: number;
  skill_id: number;
  trigger_event: string;
  equipment_id: string;
  lot_id: string;
  step: string | null;
  event_time: string | null;
  severity: string;
  title: string;
  summary: string | null;
  status: string;
  created_at: string;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  charts?: ChartDSL[] | null;
  diagnostic_results?: DiagnosticResult[];
  execution_log_id?: number | null;
  diagnostic_log_id?: number | null;
  trigger_data_views?: DataView[];
  diagnostic_data_views?: DataView[];
  diagnostic_charts?: ChartDSL[];
  diagnostic_alert?: AlertEmission;
  auto_check_runs?: AutoCheckRun[];
  // Phase 12: ack / disposition
  acked_by?: number | null;
  acked_at?: string | null;
  disposition?: string | null;
  disposition_reason?: string | null;
  disposed_by?: number | null;
  disposed_at?: string | null;
};

export function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── SSE Briefing fetcher ─────────────────────────────────────

// 2026-05-04 cost cut: in-memory briefing cache. Same (scope + cacheKey)
// returned within TTL replays the cached text instead of firing a new LLM
// stream. Re-clicks on the same alarm/cluster used to burn one call each.
// Module-scoped Map = shared across mounts within the same tab. TTL 10min
// — short enough that fresh alarm context (status flips, new evidence)
// still gets a re-render; long enough to absorb tab-switching loops.
const _BRIEFING_CACHE = new Map<string, { text: string; ts: number }>();
const _BRIEFING_TTL_MS = 10 * 60 * 1000;

export function useBriefing(scope: string, data?: string, cacheKey?: string) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const fetch_ = useCallback(async (forceFresh = false) => {
    const fullKey = `${scope}:${cacheKey ?? data ?? ""}`;
    if (!forceFresh && cacheKey) {
      const cached = _BRIEFING_CACHE.get(fullKey);
      if (cached && Date.now() - cached.ts < _BRIEFING_TTL_MS) {
        setText(cached.text);
        setLoading(false);
        return;
      }
    }

    setLoading(true);
    setText("");
    let collected = "";
    try {
      const isAlarmScope = scope === "alarm" || scope === "alarm_detail";
      let res: Response;
      if (isAlarmScope && data) {
        res = await fetch("/api/admin/briefing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope, alarmData: JSON.parse(data) }),
        });
      } else {
        const params = new URLSearchParams({ scope });
        res = await fetch(`/api/admin/briefing?${params}`);
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).replace(/^\s/, "");
          try {
            const ev = JSON.parse(payload);
            if (ev.type === "chunk") {
              collected += ev.text;
              setText(prev => prev + ev.text);
            }
          } catch { /* skip */ }
        }
      }
      if (cacheKey && collected) {
        _BRIEFING_CACHE.set(fullKey, { text: collected, ts: Date.now() });
      }
    } catch { setText("⚠️ 簡報載入失敗"); }
    finally { setLoading(false); }
  }, [scope, data, cacheKey]);

  return { text, loading, refresh: fetch_ };
}

// ── Pipeline-mode data view table ────────────────────────────

export function DataViewTable({ dv }: { dv: DataView }) {
  const cols = (dv.columns || []).slice(0, 8);
  const rows = (dv.rows || []).slice(0, 10);
  if (cols.length === 0 && rows.length === 0) {
    return <div style={{ fontSize: 12, color: "#a0aec0" }}>無資料</div>;
  }
  return (
    <div style={{
      border: "1px solid #e0e0e0", borderRadius: 6, overflow: "hidden",
      background: "#fff", marginBottom: 12,
    }}>
      {dv.title && (
        <div style={{
          padding: "8px 12px", background: "#fafafa", borderBottom: "1px solid #e0e0e0",
          fontSize: 12, fontWeight: 700, color: "#2d3748",
        }}>
          📋 {dv.title}
          {dv.total_rows > rows.length && (
            <span style={{ marginLeft: 8, fontSize: 10, color: "#999", fontWeight: 400 }}>
              ({rows.length}/{dv.total_rows} 列)
            </span>
          )}
        </div>
      )}
      {dv.description && (
        <div style={{ padding: "6px 12px", fontSize: 11, color: "#666", borderBottom: "1px solid #f0f0f0" }}>
          {dv.description}
        </div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "monospace" }}>
          <thead>
            <tr style={{ background: "#fafafa" }}>
              {cols.map((c) => (
                <th key={c} style={{
                  padding: "6px 8px", textAlign: "left", color: "#595959",
                  borderBottom: "1px solid #e0e0e0", fontWeight: 600, whiteSpace: "nowrap",
                }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} style={{ borderBottom: "1px solid #f0f0f0" }}>
                {cols.map((c) => {
                  const v = row[c];
                  const isOOC = c.endsWith("_is_ooc") && v === true;
                  const isTriggered = c === "triggered_row" && v === true;
                  const isOOCStatus = c === "spc_status" && v === "OOC";
                  const highlight = isOOC || isTriggered || isOOCStatus;
                  return (
                    <td key={c} style={{
                      padding: "6px 8px", whiteSpace: "nowrap",
                      color: highlight ? "#dc2626" : "#262626",
                      fontWeight: highlight ? 700 : 400,
                      background: highlight ? "#fff5f5" : "transparent",
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

// ── DR Accordion ─────────────────────────────────────────────

function DRAccordion({ dr, index, total }: { dr: DiagnosticResult; index: number; total: number }) {
  const isAlert = dr.findings?.condition_met === true;
  const [open, setOpen] = useState(isAlert);
  return (
    <div style={{
      border: "1px solid #e0e0e0", borderRadius: 6, marginBottom: 12,
      overflow: "hidden", background: "#fff",
    }}>
      <div onClick={() => setOpen(o => !o)} style={{
        padding: 16, cursor: "pointer",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        fontWeight: 600, fontSize: 14, transition: "background 0.15s",
        background: "#fafafa",
        borderLeft: isAlert ? "4px solid #e53e3e" : "4px solid #48bb78",
        borderBottom: open ? "1px solid #e0e0e0" : "none",
      }}>
        <span>DR {index + 1}/{total}：{dr.skill_name || `Rule #${dr.skill_id}`}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            padding: "2px 8px", borderRadius: 4, fontSize: 12, fontWeight: 700, color: "#fff",
            background: isAlert ? "#f5222d" : "#52c41a",
          }}>
            {isAlert ? "ALERT" : "PASS"}
          </span>
          <span style={{ color: "#999", fontSize: 12 }}>{open ? "▼" : "▶"}</span>
        </div>
      </div>
      {open && (
        <div style={{ padding: 16 }}>
          {dr.findings?.summary && (
            <div style={{ fontSize: 13, color: "#595959", marginBottom: 12, lineHeight: 1.5 }}>
              {dr.findings.summary}
            </div>
          )}
          {dr.findings && (
            <RenderMiddleware
              findings={dr.findings}
              outputSchema={dr.output_schema ?? []}
              charts={dr.charts ?? null}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ── Alarm Detail ─────────────────────────────────────────────

export function AlarmDetail({ alarm }: { alarm: Alarm }) {
  const drs = alarm.diagnostic_results ?? [];
  const triggerDvs = alarm.trigger_data_views ?? [];
  const diagnosticDvs = alarm.diagnostic_data_views ?? [];
  const diagnosticCharts = alarm.diagnostic_charts ?? [];
  const diagnosticAlert = alarm.diagnostic_alert ?? null;
  const autoCheckRuns = alarm.auto_check_runs ?? [];
  const hasAnyAutoCheck = autoCheckRuns.length > 0
    || diagnosticDvs.length > 0 || diagnosticCharts.length > 0 || !!diagnosticAlert;

  const findingsObj = (alarm.findings as Record<string, unknown> | null) ?? null;
  const findingsTriggered = findingsObj && (
    findingsObj.condition_met === true
    || ((findingsObj.result_summary as Record<string, unknown> | undefined)?.triggered === true)
  );
  const triggered = !!findingsTriggered || triggerDvs.length > 0 || !!alarm.summary;
  const triggerSummaryText =
    (findingsObj?.summary as string | undefined)
    ?? ((findingsObj?.result_summary as Record<string, unknown> | undefined)?.summary as string | undefined)
    ?? alarm.summary
    ?? null;

  const [detailTab, setDetailTab] = useState<"trigger" | "evidence">("trigger");

  const synthesisData = useMemo(() => JSON.stringify({
    alarm_title: alarm.title,
    equipment_id: alarm.equipment_id,
    severity: alarm.severity,
    trigger_summary: alarm.findings?.summary ?? "",
    trigger_condition_met: alarm.findings?.condition_met,
    diagnostic_rules: drs.map(dr => ({
      name: dr.skill_name,
      status: dr.status,
      condition_met: dr.findings?.condition_met,
      summary: dr.findings?.summary ?? "",
      outputs_keys: Object.keys(dr.findings?.outputs ?? {}),
    })),
    total_dr_count: drs.length,
    alert_dr_count: drs.filter(dr => dr.findings?.condition_met).length,
    pass_dr_count: drs.filter(dr => !dr.findings?.condition_met).length,
  }), [alarm, drs]);

  // Cache key = alarm.id + status — re-opening same alarm within 10min
  // replays cached text. Status change (ACK / resolved) invalidates.
  const synthesis = useBriefing("alarm_detail", synthesisData, `${alarm.id}:${alarm.status ?? ""}`);
  useEffect(() => { synthesis.refresh(); }, [alarm.id]); // eslint-disable-line

  return (
    <div>
      <h2 style={{ margin: "0 0 4px 0", fontSize: 17, color: "var(--text)" }}>
        AI 診斷報告 | {alarm.equipment_id}
      </h2>
      <p style={{ color: "var(--text-3)", marginBottom: 18, fontSize: 12 }}>
        {alarm.title} • {timeAgo(alarm.created_at)}
      </p>

      <DispositionBar alarm={alarm} />

      <div style={{
        background: "#fff",
        border: "1px solid #e2e8f0", borderLeft: "4px solid #4299e1",
        borderRadius: 8, padding: "16px 20px", marginBottom: 16,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#595959", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          ✨ AI 綜合診斷 (Synthesis)
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.6, color: "#262626" }}>
          {synthesis.loading ? (
            <span style={{ color: "#a0aec0" }}>
              <span style={{ display: "inline-block", width: 8, height: 14, background: "#1890ff", animation: "blink 1s step-end infinite", marginRight: 6, verticalAlign: "text-bottom" }} />
              AI 正在整合分析結果...
            </span>
          ) : synthesis.text ? (
            <ReactMarkdown>{synthesis.text}</ReactMarkdown>
          ) : (
            <span style={{ color: "#a0aec0" }}>（無診斷結果）</span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", borderBottom: "1px solid #e0e0e0", marginBottom: 16 }}>
        {([["trigger", "🔴 觸發原因"], ["evidence", `📊 深度診斷 (${drs.length + (autoCheckRuns.length > 0 ? autoCheckRuns.length : (hasAnyAutoCheck ? 1 : 0))})`]] as const).map(([key, label]) => (
          <button key={key} onClick={() => setDetailTab(key as "trigger" | "evidence")} style={{
            padding: "10px 20px", fontSize: 13, fontWeight: detailTab === key ? 700 : 400,
            color: detailTab === key ? "#1890ff" : "#666", cursor: "pointer",
            borderBottom: detailTab === key ? "2px solid #1890ff" : "2px solid transparent",
            background: "transparent", border: "none", transition: "0.15s",
          }}>
            {label}
          </button>
        ))}
      </div>

      {detailTab === "trigger" && (
        <div style={{ background: "#fff", border: "1px solid #e0e0e0", borderRadius: 8, padding: 20 }}>
          <div style={{
            background: "#fff",
            padding: 12, borderRadius: 4, marginBottom: 12,
            color: "#2d3748",
            border: "1px solid #e2e8f0",
            borderLeft: `4px solid ${triggered ? "#e53e3e" : "#48bb78"}`,
            fontSize: 13,
          }}>
            <div style={{ fontWeight: 700, marginBottom: 4, color: triggered ? "#dc2626" : "#16a34a" }}>
              {triggered ? "🔴 條件達成 — 已觸發警報" : "🟢 條件未達成"}
            </div>
            {triggerSummaryText && (
              <div style={{ color: "#4a5568" }}>{triggerSummaryText}</div>
            )}
          </div>

          {triggerDvs.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{
                fontSize: 11, fontWeight: 700, color: "#595959",
                textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8,
              }}>
                觸發證據（patrol pipeline 回傳）
              </div>
              {triggerDvs.map((dv, i) => <DataViewTable key={i} dv={dv} />)}
            </div>
          )}

          {triggerDvs.length === 0 && alarm.findings && Object.keys(alarm.findings).length > 0 && (
            <RenderMiddleware
              findings={alarm.findings}
              outputSchema={alarm.output_schema ?? []}
              charts={alarm.charts ?? null}
            />
          )}

          {triggerDvs.length === 0 && !alarm.findings && (
            <div style={{ color: "#a0aec0", fontSize: 13 }}>（無觸發資料）</div>
          )}
        </div>
      )}

      {detailTab === "evidence" && (
        <div>
          {autoCheckRuns.length > 0 ? (
            autoCheckRuns.map((run, idx) => {
              const dvs = run.data_views ?? [];
              const charts = run.charts ?? [];
              return (
                <DRErrorBoundary
                  key={run.run_id ?? `ac-${idx}`}
                  label={`Auto-Check ${idx + 1}/${autoCheckRuns.length}`}
                  logId={run.run_id ?? null}
                >
                  <div style={{
                    border: "1px solid #e0e0e0", borderRadius: 8,
                    padding: "14px 16px", marginBottom: 16, background: "#fff",
                  }}>
                    <div style={{
                      fontSize: 12, fontWeight: 700, color: "#1e293b",
                      marginBottom: 10,
                      display: "flex", alignItems: "center", gap: 8,
                    }}>
                      <span style={{
                        padding: "2px 8px", borderRadius: 4,
                        background: "#e0f2fe", color: "#075985",
                        fontSize: 10, fontWeight: 700, letterSpacing: "0.3px",
                      }}>AC {idx + 1}/{autoCheckRuns.length}</span>
                      <span>{run.pipeline_name || `Pipeline #${run.pipeline_id}`}</span>
                      <span style={{ marginLeft: "auto", fontSize: 11, color: "#94a3b8" }}>
                        run #{run.run_id} · {run.status}
                      </span>
                    </div>
                    {run.alert?.title && (
                      <div style={{
                        background: "#fff5f5", border: "1px solid #fca5a5",
                        borderRadius: 8, padding: "10px 14px", marginBottom: 12,
                      }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#dc2626", marginBottom: 4 }}>
                          ⚠ {run.alert.title}
                        </div>
                        {run.alert.message && (
                          <div style={{ fontSize: 12, color: "#4a5568" }}>{run.alert.message}</div>
                        )}
                      </div>
                    )}
                    {dvs.map((dv, i) => <DataViewTable key={i} dv={dv} />)}
                    {charts.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <ChartListRenderer charts={charts} />
                      </div>
                    )}
                    {dvs.length === 0 && charts.length === 0 && !run.alert && (
                      <div style={{ fontSize: 12, color: "#94a3b8" }}>（這次跑沒有產出明細）</div>
                    )}
                  </div>
                </DRErrorBoundary>
              );
            })
          ) : (
            (diagnosticDvs.length > 0 || diagnosticCharts.length > 0 || diagnosticAlert) && (
              <div style={{
                border: "1px solid #e0e0e0", borderRadius: 8,
                padding: "14px 16px", marginBottom: 16, background: "#fff",
              }}>
                <div style={{
                  fontSize: 11, fontWeight: 700, color: "#595959",
                  textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8,
                }}>
                  Auto-Check 診斷 (pipeline run #{alarm.diagnostic_log_id})
                </div>
                {diagnosticAlert?.title && (
                  <div style={{
                    background: "#fff5f5", border: "1px solid #fca5a5",
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
                  <div style={{ marginTop: 8 }}>
                    <ChartListRenderer charts={diagnosticCharts} />
                  </div>
                )}
              </div>
            )
          )}

          {drs.length > 0 && drs.map((dr, idx) => (
            <DRErrorBoundary
              key={dr.log_id ?? `dr-${idx}`}
              label={`DR ${idx + 1}/${drs.length}：${dr.skill_name || `Rule #${dr.skill_id ?? "?"}`}`}
              logId={dr.log_id ?? null}
            >
              <DRAccordion dr={dr} index={idx} total={drs.length} />
            </DRErrorBoundary>
          ))}

          {drs.length === 0 && !hasAnyAutoCheck && (
            <div style={{ padding: 24, textAlign: "center", color: "#a0aec0" }}>（無深度診斷結果）</div>
          )}
        </div>
      )}
    </div>
  );
}


// ── Phase 12: Disposition / Ack action bar ───────────────────────────
// Shows current ack + disposition state and offers buttons. Posts via
// the Next.js /api proxy which forwards to Java's /api/v1/alarms/{id}/{ack|dispose}.
// Local state mirrors the optimistic update so the bar reflects the
// new status without a full reload — the parent page can also re-fetch.

const _DISPOSITIONS: Array<{ key: string; label: string; tone: string }> = [
  { key: "release", label: "Release",  tone: "#16a34a" },
  { key: "hold",    label: "Hold",     tone: "#d97706" },
  { key: "rerun",   label: "Re-run",   tone: "#2563eb" },
  { key: "scrap",   label: "Scrap",    tone: "#dc2626" },
];

function DispositionBar({ alarm }: { alarm: Alarm }) {
  const [acked, setAcked]           = useState<boolean>(!!alarm.acked_at);
  const [disposition, setDisp]      = useState<string | null>(alarm.disposition ?? null);
  const [reason, setReason]         = useState<string>(alarm.disposition_reason ?? "");
  const [busy, setBusy]             = useState<string | null>(null);
  const [error, setError]           = useState<string | null>(null);

  const ack = useCallback(async () => {
    setBusy("ack"); setError(null);
    try {
      const r = await fetch(`/api/admin/alarms/${alarm.id}/ack`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setAcked(true);
    } catch (e) { setError(String(e)); }
    finally { setBusy(null); }
  }, [alarm.id]);

  const dispose = useCallback(async (key: string) => {
    if (!reason.trim()) { setError("請填寫處置原因"); return; }
    setBusy(key); setError(null);
    try {
      const r = await fetch(`/api/admin/alarms/${alarm.id}/dispose`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ disposition: key, reason }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDisp(key);
      setAcked(true);
    } catch (e) { setError(String(e)); }
    finally { setBusy(null); }
  }, [alarm.id, reason]);

  return (
    <div style={{
      background: "#fff",
      border: "1px solid #e2e8f0", borderLeft: "4px solid #f59e0b",
      borderRadius: 8, padding: "12px 16px", marginBottom: 16,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#595959" }}>
          🛠 處置 (Disposition)
        </span>
        <span style={{ fontSize: 11, color: "#a0aec0" }}>
          ack: {acked ? "✅ acknowledged" : "⏳ 未確認"}
          {disposition && <> ・ disposition: <strong style={{ color: "#1f2937" }}>{disposition}</strong></>}
        </span>
        {!acked && (
          <button onClick={ack} disabled={busy !== null}
            style={{ marginLeft: "auto", padding: "4px 12px", fontSize: 12, fontWeight: 600,
              background: "#f59e0b", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>
            {busy === "ack" ? "..." : "Acknowledge"}
          </button>
        )}
      </div>

      {!disposition && (
        <>
          <input
            type="text" placeholder="處置原因 (required for dispose)"
            value={reason} onChange={e => setReason(e.target.value)}
            style={{ padding: "6px 10px", fontSize: 12, border: "1px solid #d1d5db", borderRadius: 4 }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            {_DISPOSITIONS.map(d => (
              <button key={d.key}
                onClick={() => dispose(d.key)} disabled={busy !== null}
                style={{ padding: "6px 14px", fontSize: 12, fontWeight: 600,
                  background: d.tone, color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>
                {busy === d.key ? "..." : d.label}
              </button>
            ))}
          </div>
        </>
      )}

      {disposition && reason && (
        <div style={{ fontSize: 11, color: "#4a5568" }}>
          原因: <span style={{ color: "#1f2937" }}>{reason}</span>
        </div>
      )}

      {error && <div style={{ fontSize: 11, color: "#dc2626" }}>⚠ {error}</div>}
    </div>
  );
}
