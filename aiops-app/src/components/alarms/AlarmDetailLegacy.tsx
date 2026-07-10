"use client";

/**
 * Per-alarm detail UI — extracted from app/alarms/page.tsx so the new
 * cluster-first shell can compose it inside ClusterDetailPanel. The
 * tab logic, multi-run rendering, and DR accordions are preserved
 * verbatim; only the surrounding layout chrome is gone.
 */

import { useEffect, useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslations } from "next-intl";
import {
  RenderMiddleware, ChartListRenderer,
  type SkillFindings, type OutputSchemaField, type ChartDSL,
} from "@/components/operations/SkillOutputRenderer";
import { DRErrorBoundary } from "@/components/alarms/DRErrorBoundary";
import DataResultView from "@/components/common/DataResultView";

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
  // skills_v2: human trigger rule (skill.nl) + the block_step_check record
  // ({label, value, threshold, operator, note, headline, severity, ...}).
  trigger_condition?: string | null;
  check_result?: CheckResult | null;
};

export type CheckResult = {
  pass?: boolean;
  value?: unknown;
  threshold?: unknown;
  operator?: string;
  label?: string;
  headline?: string;
  note?: string;
  severity?: string;
  evidence_rows?: number;
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
  const t = useTranslations("alarms");
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
    } catch { setText(t("alarmDetail.briefingFailed")); }
    finally { setLoading(false); }
  }, [scope, data, cacheKey, t]);

  return { text, loading, refresh: fetch_ };
}

// ── Pipeline-mode data view table ────────────────────────────

/**
 * Marks the rows an operator needs to see first: an explicit triggered_row
 * flag, an OOC spc_status, or any `<chart>_is_ooc` boolean set true. The rule
 * stays here (alarm domain) rather than inside the generic DataResultView.
 */
function alarmRowHighlight(row: Record<string, unknown>): boolean {
  if (row.triggered_row === true) return true;
  if (row.spc_status === "OOC") return true;
  return Object.entries(row).some(([k, v]) => k.endsWith("_is_ooc") && v === true);
}

export function DataViewTable({ dv }: { dv: DataView }) {
  const t = useTranslations("alarms");
  const rows = dv.rows || [];
  if ((dv.columns || []).length === 0 && rows.length === 0) {
    return <div style={{ fontSize: 12, color: "#a0aec0" }}>{t("alarmDetail.noData")}</div>;
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
          {dv.title}
          {dv.total_rows > rows.length && (
            <span style={{ marginLeft: 8, fontSize: 10, color: "#999", fontWeight: 400 }}>
              {t("alarmDetail.totalRows", { n: dv.total_rows })}
            </span>
          )}
        </div>
      )}
      {dv.description && (
        <div style={{ padding: "6px 12px", fontSize: 11, color: "#666", borderBottom: "1px solid #f0f0f0" }}>
          {dv.description}
        </div>
      )}
      <div style={{ height: 300, display: "flex", flexDirection: "column", padding: 10 }}>
        <DataResultView result={rows} enableFullscreen={false} emptyText={t("alarmDetail.noData")} rowHighlight={alarmRowHighlight} />
      </div>
    </div>
  );
}

// ── DR Accordion ─────────────────────────────────────────────

function DRAccordion({ dr, index, total }: { dr: DiagnosticResult; index: number; total: number }) {
  const t = useTranslations("alarms");
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
        <span>{t("alarmDetail.drHeader", { index: index + 1, total, name: dr.skill_name || t("alarmDetail.ruleFallback", { id: dr.skill_id ?? "?" }) })}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            padding: "2px 8px", borderRadius: 4, fontSize: 12, fontWeight: 700, color: "#fff",
            background: isAlert ? "#f5222d" : "#52c41a",
          }}>
            {isAlert ? t("alarmDetail.badgeAlert") : t("alarmDetail.badgePass")}
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

/** Labelled section block used by the trigger tab (rule / why-met). */
function AlarmSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{
      border: "1px solid #e2e8f0", borderLeft: "4px solid var(--p, #4f46e5)",
      borderRadius: 6, padding: "12px 14px", marginBottom: 12, background: "#fbfcff",
    }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: "var(--p, #4f46e5)",
        textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6,
      }}>{label}</div>
      {children}
    </div>
  );
}

export function AlarmDetail({ alarm }: { alarm: Alarm }) {
  const t = useTranslations("alarms");
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
        {t("detail.synthesisTitle", { id: alarm.equipment_id })}
      </h2>
      <p style={{ color: "var(--text-3)", marginBottom: 18, fontSize: 12 }}>
        {alarm.title} • {timeAgo(alarm.created_at)}
      </p>

      <DispositionBar alarm={alarm} />

      <div style={{
        background: "#fff",
        border: "1px solid #e2e8f0", borderLeft: "4px solid var(--p, #4299e1)",
        borderRadius: 8, padding: "16px 20px", marginBottom: 16,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#595959", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          ✨ {t("alarmDetail.synthesisHeading")}
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.6, color: "#262626" }}>
          {synthesis.loading ? (
            <span style={{ color: "#a0aec0" }}>
              <span style={{ display: "inline-block", width: 8, height: 14, background: "#1890ff", animation: "blink 1s step-end infinite", marginRight: 6, verticalAlign: "text-bottom" }} />
              {t("alarmDetail.integrating")}
            </span>
          ) : synthesis.text ? (
            <ReactMarkdown>{synthesis.text}</ReactMarkdown>
          ) : (
            <span style={{ color: "#a0aec0" }}>{t("alarmDetail.noDiagnosis")}</span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", borderBottom: "1px solid #e0e0e0", marginBottom: 16 }}>
        {([["trigger", `🔴 ${t("alarmDetail.tabTrigger")}`], ["evidence", `📊 ${t("alarmDetail.tabEvidence", { n: drs.length + (autoCheckRuns.length > 0 ? autoCheckRuns.length : (hasAnyAutoCheck ? 1 : 0)) })}`]] as const).map(([key, label]) => (
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
          {/* 觸發條件（規則）— human rule from skill.nl */}
          {alarm.trigger_condition && (
            <AlarmSection label={t("alarmDetail.sectionRule")}>
              <div style={{ fontSize: 13, color: "#2d3748", whiteSpace: "pre-line", lineHeight: 1.6 }}>
                {alarm.trigger_condition}
              </div>
            </AlarmSection>
          )}

          {/* 為什麼達標 — measured value vs threshold, from block_step_check */}
          {alarm.check_result && (
            <AlarmSection label={t("alarmDetail.sectionWhy")}>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#dc2626", marginBottom: 8 }}>
                {alarm.check_result.headline ?? alarm.check_result.note ?? t("alarmDetail.conditionMetFallback")}
              </div>
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12, color: "#4a5568", fontFamily: "ui-monospace, monospace" }}>
                {alarm.check_result.label && <span>{t.rich("alarmDetail.measured", { label: alarm.check_result.label, b: chunks => <b>{chunks}</b> })}</span>}
                <span>{t.rich("alarmDetail.actualValue", { v: String(alarm.check_result.value ?? "—"), b: chunks => <b style={{ color: "var(--p, #1d4ed8)" }}>{chunks}</b> })}</span>
                <span>{t.rich("alarmDetail.thresholdExpr", { op: alarm.check_result.operator ?? "", v: String(alarm.check_result.threshold ?? "—"), b: chunks => <b>{chunks}</b> })}</span>
                {alarm.check_result.evidence_rows != null && <span style={{ color: "#94a3b8" }}>{t("alarmDetail.scanned", { n: alarm.check_result.evidence_rows })}</span>}
              </div>
            </AlarmSection>
          )}

          <div style={{
            background: "#fff",
            padding: 12, borderRadius: 4, marginBottom: 12,
            color: "#2d3748",
            border: "1px solid #e2e8f0",
            borderLeft: `4px solid ${triggered ? "#e53e3e" : "#48bb78"}`,
            fontSize: 13,
          }}>
            <div style={{ fontWeight: 700, marginBottom: 4, color: triggered ? "#dc2626" : "#16a34a" }}>
              {triggered ? `🔴 ${t("alarmDetail.conditionMet")}` : `🟢 ${t("alarmDetail.conditionNotMet")}`}
            </div>
            {/* Headline already shown in 為什麼達標 above; only show raw summary when no structured check exists. */}
            {!alarm.check_result && triggerSummaryText && (
              <div style={{ color: "#4a5568", whiteSpace: "pre-line" }}>{triggerSummaryText}</div>
            )}
          </div>

          {triggerDvs.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{
                fontSize: 11, fontWeight: 700, color: "#595959",
                textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8,
              }}>
                {t("alarmDetail.triggerEvidence")}
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
            <div style={{ color: "#a0aec0", fontSize: 13 }}>{t("alarmDetail.noTriggerData")}</div>
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
                  label={t("alarmDetail.autoCheckLabel", { index: idx + 1, total: autoCheckRuns.length })}
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
                      <div style={{ fontSize: 12, color: "#94a3b8" }}>{t("alarmDetail.noRunOutput")}</div>
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
                  {alarm.diagnostic_log_id
                    ? t("alarmDetail.acDiagHeading", { id: alarm.diagnostic_log_id })
                    : t("alarmDetail.skillDeepCheck")}
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
              label={t("alarmDetail.drHeader", { index: idx + 1, total: drs.length, name: dr.skill_name || t("alarmDetail.ruleFallback", { id: dr.skill_id ?? "?" }) })}
              logId={dr.log_id ?? null}
            >
              <DRAccordion dr={dr} index={idx} total={drs.length} />
            </DRErrorBoundary>
          ))}

          {drs.length === 0 && !hasAnyAutoCheck && (
            <div style={{ padding: 24, textAlign: "center", color: "#a0aec0" }}>{t("alarmDetail.noDeepResults")}</div>
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

const _DISPOSITIONS: Array<{ key: string; labelKey: string; tone: string }> = [
  { key: "release", labelKey: "dispo.release", tone: "#16a34a" },
  { key: "hold",    labelKey: "dispo.hold",    tone: "#d97706" },
  { key: "rerun",   labelKey: "dispo.rerun",   tone: "var(--p, #2563eb)" },
  { key: "scrap",   labelKey: "dispo.scrap",   tone: "#dc2626" },
];

function DispositionBar({ alarm }: { alarm: Alarm }) {
  const t = useTranslations("alarms");
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
    if (!reason.trim()) { setError(t("dispo.reasonRequired")); return; }
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
  }, [alarm.id, reason, t]);

  return (
    <div style={{
      background: "#fff",
      border: "1px solid #e2e8f0", borderLeft: "4px solid #f59e0b",
      borderRadius: 8, padding: "12px 16px", marginBottom: 16,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#595959" }}>
          🛠 {t("dispo.heading")}
        </span>
        <span style={{ fontSize: 11, color: "#a0aec0" }}>
          {t("dispo.ackLabel")} {acked ? t("dispo.acked") : t("dispo.pending")}
          {disposition && <> ・ {t("dispo.dispositionLabel")} <strong style={{ color: "#1f2937" }}>{disposition}</strong></>}
        </span>
        {!acked && (
          <button onClick={ack} disabled={busy !== null}
            style={{ marginLeft: "auto", padding: "4px 12px", fontSize: 12, fontWeight: 600,
              background: "#f59e0b", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>
            {busy === "ack" ? "..." : t("dispo.ackButton")}
          </button>
        )}
      </div>

      {!disposition && (
        <>
          <input
            type="text" placeholder={t("dispo.reasonPlaceholder")}
            value={reason} onChange={e => setReason(e.target.value)}
            style={{ padding: "6px 10px", fontSize: 12, border: "1px solid #d1d5db", borderRadius: 4 }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            {_DISPOSITIONS.map(d => (
              <button key={d.key}
                onClick={() => dispose(d.key)} disabled={busy !== null}
                style={{ padding: "6px 14px", fontSize: 12, fontWeight: 600,
                  background: d.tone, color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>
                {busy === d.key ? "..." : t(d.labelKey)}
              </button>
            ))}
          </div>
        </>
      )}

      {disposition && reason && (
        <div style={{ fontSize: 11, color: "#4a5568" }}>
          {t("dispo.reasonLabel")} <span style={{ color: "#1f2937" }}>{reason}</span>
        </div>
      )}

      {error && <div style={{ fontSize: 11, color: "#dc2626" }}>⚠ {error}</div>}
    </div>
  );
}
