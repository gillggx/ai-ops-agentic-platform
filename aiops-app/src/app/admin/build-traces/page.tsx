"use client";

import { useEffect, useMemo, useState } from "react";
import ChartRenderer from "@/components/pipeline-builder/ChartRenderer";

// ============================================================================
// Design tokens
// ============================================================================

const T = {
  // Surfaces
  bgPage: "#f6f8fa",
  bgCard: "#ffffff",
  bgSubtle: "#f9fafb",
  bgInput: "#ffffff",
  bgCode: "#0f172a",

  // Text
  text: "#0f172a",
  textMuted: "#64748b",
  textSubtle: "#94a3b8",
  textInverse: "#f1f5f9",

  // Borders
  border: "#e2e8f0",
  borderStrong: "#cbd5e1",

  // Accent
  accent: "#3b82f6",
  accentSoft: "#eff6ff",
  accentBorder: "#bfdbfe",

  // Status
  success: "#059669",
  successSoft: "#d1fae5",
  warning: "#d97706",
  warningSoft: "#fef3c7",
  danger: "#dc2626",
  dangerSoft: "#fee2e2",
  neutral: "#64748b",
  neutralSoft: "#f1f5f9",
  llm: "#7c3aed",
  llmSoft: "#ede9fe",

  // Geometry
  radius: 8,
  radiusSm: 6,
  shadowSm: "0 1px 2px rgba(0, 0, 0, 0.04)",
  shadow: "0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)",
  shadowLg: "0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.04)",

  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", system-ui, sans-serif',
  fontMono: 'ui-monospace, SF Mono, Menlo, Monaco, "Cascadia Code", monospace',
};

const STATUS_META: Record<string, { color: string; bg: string; label: string }> = {
  finished:           { color: T.success, bg: T.successSoft, label: "Finished" },
  plan_unfixable:     { color: T.danger,  bg: T.dangerSoft,  label: "Unfixable" },
  failed:             { color: T.danger,  bg: T.dangerSoft,  label: "Failed" },
  failed_structural:  { color: T.danger,  bg: T.dangerSoft,  label: "Structural error" },
  needs_confirm:      { color: T.warning, bg: T.warningSoft, label: "Awaiting confirm" },
  cancelled:          { color: T.neutral, bg: T.neutralSoft, label: "Cancelled" },
  ok:                 { color: T.success, bg: T.successSoft, label: "OK" },
  success:            { color: T.success, bg: T.successSoft, label: "Success" },
  partial:            { color: T.warning, bg: T.warningSoft, label: "Partial" },
  error:              { color: T.danger,  bg: T.dangerSoft,  label: "Error" },
  skipped:            { color: T.neutral, bg: T.neutralSoft, label: "Skipped" },
};

// ============================================================================
// Types
// ============================================================================

interface TraceListItem {
  file: string;
  build_id?: string;
  session_id?: string;
  started_at?: string;
  duration_ms?: number;
  status?: string;
  instruction?: string;
  n_steps: number;
  n_llm: number;
  n_nodes: number;
  n_edges: number;
}

type GraphStep = Record<string, unknown> & {
  node?: string;
  ts?: string;
  status?: string;
  duration_ms?: number;
  step_idx?: number;
  step_text?: string;
  n_ops?: number;
  attempts?: number;
  autofixes?: string[];
  ops_emitted?: Array<Record<string, unknown>>;
  node_results?: Record<string, NodeRunResult>;
};

type LlmCall = Record<string, unknown> & {
  node?: string;
  ts?: string;
  attempt?: number;
  user_msg?: string;
  raw_response?: string;
  parsed?: unknown;
  step_idx?: number;
};

type NodeRunResult = {
  status?: string;
  rows?: number | null;
  duration_ms?: number;
  error?: string;
  ports?: Record<string, {
    kind?: string;
    // dataframe
    columns?: string[];
    total?: number;
    rows?: Array<Record<string, unknown>>;
    first_row?: Record<string, unknown> | null;  // legacy compact shape
    // chart_spec — full snapshot so renderer can draw
    snapshot?: Record<string, unknown>;
    chart_type?: string;
    title?: string;
    n_data_points?: number | null;
    // bool / dict / list
    value?: unknown;
    keys?: string[];
    length?: number;
    sample?: unknown;
  }>;
};

type PipelineNode = { id: string; block_id: string; params?: Record<string, unknown> };
type PipelineEdge = { id?: string; from?: { node: string; port: string }; to?: { node: string; port: string } };

interface TraceDetail {
  build_id?: string;
  session_id?: string;
  status?: string;
  duration_ms?: number;
  started_at?: string;
  finished_at?: string;
  instruction?: string;
  graph_steps?: GraphStep[];
  llm_calls?: LlmCall[];
  final_pipeline?: { nodes?: PipelineNode[]; edges?: PipelineEdge[] };
}

type ExecuteResult = {
  status?: string;
  duration_ms?: number;
  node_results?: Record<string, RawNodeResult>;
  error_message?: string;
};

type RawNodeResult = {
  status?: string;
  rows?: number | null;
  duration_ms?: number;
  error?: string;
  preview?: Record<string, RawPreviewBlob>;
};

type RawPreviewBlob = {
  type?: string;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  sample_rows?: Array<Record<string, unknown>>;
  total?: number;
  snapshot?: { type?: string; title?: string; data?: unknown[] };
  value?: unknown;
};

// ============================================================================
// Formatters
// ============================================================================

function fmtTime(iso?: string): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

function fmtTimeShort(iso?: string): string {
  if (!iso) return "—";
  const m = iso.match(/T(\d{2}:\d{2}:\d{2})(\.\d{3})?/);
  return m ? m[1] : iso;
}

function fmtDuration(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60_000);
  const sec = Math.floor((ms % 60_000) / 1000);
  return `${min}m${sec}s`;
}

function fmtRelTime(iso?: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

// ============================================================================
// Page
// ============================================================================

export default function BuildTracesPage() {
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [traceDir, setTraceDir] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [tab, setTab] = useState<"journey" | "results" | "pipeline">("journey");
  const [reRun, setReRun] = useState<ExecuteResult | null>(null);
  const [reRunLoading, setReRunLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    fetch("/api/admin/build-traces")
      .then((r) => r.json())
      .then((data) => {
        if (!mounted) return;
        if (data.error) setError(data.error);
        else {
          setTraces(data.traces || []);
          setTraceDir(data.dir || "");
        }
      })
      .catch((e) => mounted && setError(String(e)))
      .finally(() => mounted && setLoading(false));
    return () => { mounted = false; };
  }, []);

  function loadDetail(file: string) {
    setSelectedFile(file);
    setDetailLoading(true);
    setDetail(null);
    setReRun(null);
    setTab("journey");
    fetch(`/api/admin/build-traces/${encodeURIComponent(file)}`)
      .then((r) => r.json())
      .then((data) => setDetail(data))
      .catch((e) => setDetail({ status: "fetch error: " + String(e) }))
      .finally(() => setDetailLoading(false));
  }

  function reRunPipeline() {
    if (!detail?.final_pipeline) return;
    setReRunLoading(true);
    setReRun(null);
    fetch("/api/admin/build-traces/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pipeline_json: detail.final_pipeline }),
    })
      .then((r) => r.json())
      .then((data) => setReRun(data))
      .catch((e) => setReRun({ status: "error", error_message: String(e) }))
      .finally(() => setReRunLoading(false));
  }

  const filtered = useMemo(() => {
    const ql = search.trim().toLowerCase();
    return traces.filter((t) => {
      if (statusFilter && t.status !== statusFilter) return false;
      if (ql && !((t.instruction || "").toLowerCase().includes(ql) || (t.build_id || "").includes(ql))) return false;
      return true;
    });
  }, [traces, statusFilter, search]);

  const statusCounts = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const t of traces) {
      const s = t.status || "(none)";
      acc[s] = (acc[s] || 0) + 1;
    }
    return acc;
  }, [traces]);

  return (
    <div style={{
      display: "flex",
      height: "calc(100vh - 64px)",
      margin: -32,
      background: T.bgPage,
      fontFamily: T.font,
      color: T.text,
    }}>
      {/* Master list */}
      <aside style={{
        width: 460,
        borderRight: `1px solid ${T.border}`,
        background: T.bgCard,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
      }}>
        <header style={{ padding: "20px 20px 12px", borderBottom: `1px solid ${T.border}` }}>
          <h1 style={{
            margin: 0,
            fontSize: 18,
            fontWeight: 600,
            letterSpacing: -0.2,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}>
            <span style={{ fontSize: 22 }}>📜</span>
            Build Traces
          </h1>
          <div style={{ fontSize: 12, color: T.textSubtle, marginTop: 4, fontFamily: T.fontMono }}>
            {traceDir} · {filtered.length}/{traces.length}
          </div>

          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="🔍 search instruction / build_id..."
            style={{
              width: "100%",
              marginTop: 12,
              padding: "8px 10px",
              border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm,
              fontSize: 13,
              background: T.bgInput,
              color: T.text,
              outline: "none",
              boxSizing: "border-box",
            }}
          />

          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 10 }}>
            <Pill label="all" count={traces.length} active={statusFilter === ""} onClick={() => setStatusFilter("")} />
            {Object.entries(statusCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([s, n]) => (
                <Pill
                  key={s}
                  label={STATUS_META[s]?.label ?? s}
                  count={n}
                  active={statusFilter === s}
                  color={STATUS_META[s]?.color}
                  bg={STATUS_META[s]?.bg}
                  onClick={() => setStatusFilter(s)}
                />
              ))}
          </div>
        </header>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <div style={{ padding: 24, color: T.textMuted, textAlign: "center" }}>Loading…</div>}
          {error && <div style={{ padding: 16, color: T.danger, fontSize: 13 }}>Error: {error}</div>}
          {!loading && !error && filtered.length === 0 && (
            <div style={{ padding: 32, color: T.textSubtle, textAlign: "center", fontSize: 13 }}>
              No traces match.
            </div>
          )}
          {filtered.map((t) => (
            <TraceListRow
              key={t.file}
              trace={t}
              selected={selectedFile === t.file}
              onClick={() => loadDetail(t.file)}
            />
          ))}
        </div>
      </aside>

      {/* Detail */}
      <main style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", minWidth: 0 }}>
        {!selectedFile && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: T.textSubtle }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>👈</div>
              <div style={{ fontSize: 14 }}>Select a trace from the list to inspect.</div>
            </div>
          </div>
        )}
        {detailLoading && (
          <div style={{ padding: 32, color: T.textMuted, textAlign: "center" }}>Loading trace…</div>
        )}
        {detail && (
          <>
            <DetailHeader detail={detail} tab={tab} setTab={setTab} onReRun={reRunPipeline} reRunLoading={reRunLoading} reRun={reRun} />
            <div style={{ flex: 1, padding: 24 }}>
              {tab === "journey" && <JourneyTab detail={detail} />}
              {tab === "results" && <ResultsTab detail={detail} reRun={reRun} />}
              {tab === "pipeline" && <PipelineTab detail={detail} />}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

// ============================================================================
// Master list row
// ============================================================================

function TraceListRow({ trace, selected, onClick }: { trace: TraceListItem; selected: boolean; onClick: () => void }) {
  const meta = STATUS_META[trace.status || ""] ?? { color: T.neutral, bg: T.neutralSoft, label: trace.status || "—" };
  return (
    <div
      onClick={onClick}
      style={{
        padding: "12px 20px",
        borderBottom: `1px solid ${T.border}`,
        background: selected ? T.accentSoft : T.bgCard,
        borderLeft: selected ? `3px solid ${T.accent}` : "3px solid transparent",
        cursor: "pointer",
        transition: "background 0.15s",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <StatusBadge status={trace.status} />
        <span style={{ fontSize: 11, color: T.textMuted, fontFamily: T.fontMono }}>
          {fmtTimeShort(trace.started_at)}
        </span>
        <span style={{ fontSize: 11, color: T.textSubtle }}>
          {fmtRelTime(trace.started_at)}
        </span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: T.textMuted, fontFamily: T.fontMono }}>
          {fmtDuration(trace.duration_ms)}
        </span>
      </div>
      <div style={{
        fontSize: 13,
        color: T.text,
        lineHeight: 1.4,
        overflow: "hidden",
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical",
      }}>
        {trace.instruction || "(no instruction)"}
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: 11, color: T.textSubtle }}>
        <span title="graph steps">⎏ {trace.n_steps}</span>
        <span title="LLM calls" style={{ color: T.llm }}>✺ {trace.n_llm}</span>
        <span title="nodes/edges">⬡ {trace.n_nodes}/{trace.n_edges}</span>
        <span style={{ marginLeft: "auto", fontFamily: T.fontMono, color: T.textSubtle }}>
          {(trace.build_id || "").slice(0, 8)}
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// Detail header (sticky)
// ============================================================================

function DetailHeader({
  detail, tab, setTab, onReRun, reRunLoading, reRun,
}: {
  detail: TraceDetail; tab: string; setTab: (t: "journey" | "results" | "pipeline") => void;
  onReRun: () => void; reRunLoading: boolean; reRun: ExecuteResult | null;
}) {
  return (
    <div style={{
      position: "sticky",
      top: 0,
      zIndex: 10,
      background: T.bgCard,
      borderBottom: `1px solid ${T.border}`,
      padding: "20px 24px 0",
      boxShadow: T.shadowSm,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <StatusBadge status={detail.status} large />
        <h2 style={{ margin: 0, fontSize: 16, fontFamily: T.fontMono, color: T.text, fontWeight: 600 }}>
          {detail.build_id}
        </h2>
        <span style={{ fontSize: 12, color: T.textSubtle, fontFamily: T.fontMono }}>
          ⏱ {fmtDuration(detail.duration_ms)}
        </span>
        <span style={{ fontSize: 12, color: T.textSubtle, fontFamily: T.fontMono }}>
          📅 {fmtTime(detail.started_at)}
        </span>
        <span style={{ fontSize: 12, color: T.textSubtle, fontFamily: T.fontMono, marginLeft: "auto" }}>
          session: {(detail.session_id || "").slice(0, 12)}
        </span>
      </div>
      <div style={{ fontSize: 13, color: T.textMuted, lineHeight: 1.5, marginBottom: 12, paddingBottom: 12, borderBottom: `1px solid ${T.border}` }}>
        {detail.instruction}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 0 }}>
        {([
          { id: "journey", label: "Journey", icon: "📜", count: (detail.graph_steps?.length || 0) + (detail.llm_calls?.length || 0) },
          { id: "results", label: "Results", icon: "📊", count: detail.final_pipeline?.nodes?.length || 0 },
          { id: "pipeline", label: "Pipeline", icon: "🧩", count: detail.final_pipeline?.nodes?.length || 0 },
        ] as const).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id as "journey" | "results" | "pipeline")}
            style={{
              padding: "10px 16px",
              border: "none",
              borderBottom: tab === t.id ? `2px solid ${T.accent}` : "2px solid transparent",
              background: "transparent",
              color: tab === t.id ? T.accent : T.textMuted,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: tab === t.id ? 600 : 500,
              fontFamily: T.font,
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: -1,
            }}
          >
            <span>{t.icon}</span>
            {t.label}
            <span style={{
              fontSize: 11,
              padding: "1px 6px",
              background: tab === t.id ? T.accentSoft : T.neutralSoft,
              color: tab === t.id ? T.accent : T.textMuted,
              borderRadius: 10,
              fontFamily: T.fontMono,
            }}>
              {t.count}
            </span>
          </button>
        ))}

        <button
          onClick={onReRun}
          disabled={reRunLoading || !detail.final_pipeline}
          style={{
            marginLeft: "auto",
            marginBottom: 8,
            padding: "8px 14px",
            border: "none",
            background: reRunLoading ? T.accentBorder : T.accent,
            color: "#fff",
            cursor: reRunLoading ? "wait" : "pointer",
            fontSize: 13,
            fontWeight: 600,
            borderRadius: T.radiusSm,
            display: "flex",
            alignItems: "center",
            gap: 6,
            transition: "background 0.15s",
            boxShadow: T.shadowSm,
          }}
        >
          {reRunLoading ? "⟳ Running…" : "▶ Re-run pipeline"}
        </button>
        {reRun && reRun.status && (
          <span style={{
            marginLeft: 12,
            marginBottom: 8,
            padding: "4px 10px",
            background: STATUS_META[reRun.status]?.bg ?? T.neutralSoft,
            color: STATUS_META[reRun.status]?.color ?? T.text,
            fontSize: 12,
            borderRadius: T.radiusSm,
            fontWeight: 500,
          }}>
            re-run: {reRun.status} · {fmtDuration(reRun.duration_ms)}
            {reRun.error_message && ` · ${reRun.error_message.slice(0, 60)}`}
          </span>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Status badge
// ============================================================================

function StatusBadge({ status, large }: { status?: string; large?: boolean }) {
  const meta = STATUS_META[status || ""] ?? { color: T.neutral, bg: T.neutralSoft, label: status || "—" };
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      padding: large ? "4px 12px" : "2px 8px",
      background: meta.bg,
      color: meta.color,
      borderRadius: 12,
      fontSize: large ? 12 : 11,
      fontWeight: 600,
      letterSpacing: 0.2,
    }}>
      {meta.label}
    </span>
  );
}

function Pill({ label, count, active, color, bg, onClick }: {
  label: string; count?: number; active: boolean; color?: string; bg?: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 10px",
        border: "none",
        background: active ? (color ?? T.text) : (bg ?? T.neutralSoft),
        color: active ? "#fff" : (color ?? T.textMuted),
        borderRadius: 12,
        fontSize: 11,
        cursor: "pointer",
        fontWeight: 500,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        transition: "all 0.15s",
      }}
    >
      {label}
      {count != null && (
        <span style={{
          padding: "0 5px",
          background: active ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.05)",
          borderRadius: 8,
          fontSize: 10,
          fontFamily: T.fontMono,
        }}>{count}</span>
      )}
    </button>
  );
}

// ============================================================================
// Journey timeline
// ============================================================================

function JourneyTab({ detail }: { detail: TraceDetail }) {
  type Item = { ts?: string; kind: "step" | "llm"; data: GraphStep | LlmCall };
  const items: Item[] = useMemo(() => {
    const out: Item[] = [];
    for (const s of detail.graph_steps || []) out.push({ ts: s.ts, kind: "step", data: s });
    for (const c of detail.llm_calls || []) out.push({ ts: c.ts, kind: "llm", data: c });
    out.sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
    return out;
  }, [detail]);

  if (items.length === 0) {
    return <EmptyState icon="📜" text="No timeline events recorded." />;
  }

  return (
    <div style={{ position: "relative", paddingLeft: 28 }}>
      {/* Vertical timeline line */}
      <div style={{
        position: "absolute",
        left: 11,
        top: 8,
        bottom: 8,
        width: 2,
        background: T.border,
      }} />
      {items.map((it, i) => (
        <TimelineCard key={i} item={it} />
      ))}
    </div>
  );
}

function TimelineCard({ item }: { item: { ts?: string; kind: "step" | "llm"; data: GraphStep | LlmCall } }) {
  const data = item.data;
  const isLlm = item.kind === "llm";
  const node = data.node || "?";
  const failed = (data as GraphStep).status === "failed";
  const dotColor = failed ? T.danger : isLlm ? T.llm : T.success;
  const tagBg = isLlm ? T.llmSoft : (failed ? T.dangerSoft : T.successSoft);
  const tagColor = isLlm ? T.llm : (failed ? T.danger : T.success);

  return (
    <div style={{ position: "relative", marginBottom: 12 }}>
      {/* Timeline dot */}
      <div style={{
        position: "absolute",
        left: -22,
        top: 12,
        width: 12,
        height: 12,
        borderRadius: 6,
        background: dotColor,
        border: `3px solid ${T.bgPage}`,
        boxShadow: `0 0 0 1px ${T.border}`,
        zIndex: 1,
      }} />

      <div style={{
        background: T.bgCard,
        border: `1px solid ${T.border}`,
        borderRadius: T.radius,
        padding: 12,
        boxShadow: T.shadowSm,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
          <span style={{ fontFamily: T.fontMono, color: T.textSubtle, fontSize: 11 }}>
            {fmtTimeShort(item.ts)}
          </span>
          <span style={{
            padding: "1px 8px",
            background: tagBg,
            color: tagColor,
            borderRadius: 10,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 0.3,
          }}>{isLlm ? "LLM" : "STEP"}</span>
          <b style={{ fontSize: 13, color: T.text }}>{node}</b>
          {(data as GraphStep).step_idx != null && (
            <span style={{ color: T.textMuted, fontSize: 11, fontFamily: T.fontMono }}>
              step_{(data as GraphStep).step_idx}
            </span>
          )}
          {(data as LlmCall).attempt != null && (data as LlmCall).attempt! > 1 && (
            <span style={{
              padding: "1px 6px",
              background: T.warningSoft,
              color: T.warning,
              borderRadius: 8,
              fontSize: 10,
              fontWeight: 600,
            }}>retry #{(data as LlmCall).attempt}</span>
          )}
          {(data as GraphStep).duration_ms != null && (
            <span style={{ marginLeft: "auto", color: T.textSubtle, fontSize: 11, fontFamily: T.fontMono }}>
              {fmtDuration((data as GraphStep).duration_ms)}
            </span>
          )}
        </div>
        {(data as GraphStep).step_text && (
          <div style={{
            fontSize: 12,
            color: T.text,
            background: T.accentSoft,
            border: `1px solid ${T.accentBorder}`,
            padding: "6px 10px",
            borderRadius: T.radiusSm,
            marginTop: 8,
          }}>
            <span style={{ color: T.accent, fontWeight: 600, marginRight: 6 }}>📋</span>
            {(data as GraphStep).step_text}
          </div>
        )}
        {Array.isArray((data as GraphStep).autofixes) && ((data as GraphStep).autofixes as string[]).length > 0 && (
          <div style={{ marginTop: 8 }}>
            {((data as GraphStep).autofixes as string[]).map((n: string, i: number) => (
              <div key={i} style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 6,
                fontSize: 11,
                color: T.warning,
                background: T.warningSoft,
                padding: "4px 8px",
                borderRadius: T.radiusSm,
                marginTop: 4,
              }}>
                <span style={{ flexShrink: 0 }}>⚙</span>
                <span style={{ lineHeight: 1.4 }}>{n}</span>
              </div>
            ))}
          </div>
        )}
        {Array.isArray((data as GraphStep).ops_emitted) && ((data as GraphStep).ops_emitted as Array<unknown>).length > 0 && (
          <Collapsible label={`ops emitted (${((data as GraphStep).ops_emitted as Array<unknown>).length})`}>
            <CodeBlock json={(data as GraphStep).ops_emitted} />
          </Collapsible>
        )}
        {(data as GraphStep).node_results && (
          <Collapsible label="🎯 dry-run results" defaultOpen color={T.accent}>
            <CodeBlock json={(data as GraphStep).node_results} />
          </Collapsible>
        )}
        {isLlm && (
          <div style={{ marginTop: 6 }}>
            <ModelDecision call={data as LlmCall} />
            <Collapsible label={`📥 user_msg (${((data as LlmCall).user_msg || "").length} chars)`} color={T.llm}>
              <CodeBlock text={(data as LlmCall).user_msg || ""} />
            </Collapsible>
            <Collapsible label="📤 raw_response" color={T.llm}>
              <CodeBlock text={(data as LlmCall).raw_response || ""} />
            </Collapsible>
            {(data as LlmCall).parsed != null && (
              <Collapsible label="🔍 parsed (raw)" color={T.llm}>
                <CodeBlock json={(data as LlmCall).parsed} />
              </Collapsible>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Results tab
// ============================================================================

// ── Model decision: surface the LLM's structured output prominently ──
function ModelDecision({ call }: { call: LlmCall }) {
  const node = call.node || "";
  const parsed = call.parsed as Record<string, unknown> | null | undefined;
  if (!parsed || typeof parsed !== "object") return null;

  // macro_plan_node — show the planned steps as a numbered list
  if (node === "macro_plan_node" && Array.isArray((parsed as Record<string, unknown>).macro_plan)) {
    const steps = (parsed as { macro_plan: Array<Record<string, unknown>> }).macro_plan;
    const summary = (parsed as Record<string, unknown>).plan_summary as string | undefined;
    return (
      <div style={{
        marginTop: 6,
        padding: 10,
        background: T.llmSoft,
        border: `1px solid ${T.llm}33`,
        borderRadius: T.radiusSm,
      }}>
        <div style={{ fontSize: 11, color: T.llm, fontWeight: 600, marginBottom: 6, letterSpacing: 0.3 }}>
          🧠 MODEL DECISION · macro plan
        </div>
        {summary && (
          <div style={{ fontSize: 12, color: T.text, marginBottom: 8, fontStyle: "italic" }}>
            {summary}
          </div>
        )}
        <ol style={{ margin: 0, paddingLeft: 22, fontSize: 12, color: T.text }}>
          {steps.map((s, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              <span style={{
                padding: "1px 6px",
                background: "#fff",
                border: `1px solid ${T.llm}55`,
                color: T.llm,
                borderRadius: 4,
                fontSize: 10,
                fontFamily: T.fontMono,
                marginRight: 6,
              }}>
                {(s.expected_kind as string) || "?"}
              </span>
              {String(s.text || "(no text)")}
              {s.candidate_block && (
                <span style={{ color: T.textMuted, fontSize: 11, marginLeft: 6, fontFamily: T.fontMono }}>
                  → {String(s.candidate_block)}
                </span>
              )}
            </li>
          ))}
        </ol>
      </div>
    );
  }

  // compile_chunk_node — show the ops the model proposed
  if (node === "compile_chunk_node" && Array.isArray((parsed as Record<string, unknown>).ops)) {
    const ops = (parsed as { ops: Array<Record<string, unknown>> }).ops;
    const reason = (parsed as Record<string, unknown>).reason as string | undefined;
    return (
      <div style={{
        marginTop: 6,
        padding: 10,
        background: T.llmSoft,
        border: `1px solid ${T.llm}33`,
        borderRadius: T.radiusSm,
      }}>
        <div style={{ fontSize: 11, color: T.llm, fontWeight: 600, marginBottom: 6, letterSpacing: 0.3 }}>
          🧠 MODEL DECISION · ops to dispatch
        </div>
        {reason && (
          <div style={{ fontSize: 12, color: T.text, marginBottom: 8, fontStyle: "italic" }}>
            {reason}
          </div>
        )}
        {ops.map((op, i) => (
          <OpRow key={i} op={op} />
        ))}
      </div>
    );
  }

  // clarify_intent — show the questions
  if (node === "clarify_intent_node" && Array.isArray((parsed as Record<string, unknown>).clarifications)) {
    const qs = (parsed as { clarifications: Array<Record<string, unknown>> }).clarifications;
    return (
      <div style={{
        marginTop: 6,
        padding: 10,
        background: T.llmSoft,
        border: `1px solid ${T.llm}33`,
        borderRadius: T.radiusSm,
      }}>
        <div style={{ fontSize: 11, color: T.llm, fontWeight: 600, marginBottom: 6, letterSpacing: 0.3 }}>
          🧠 MODEL DECISION · clarification needed
        </div>
        {qs.map((q, i) => (
          <div key={i} style={{ fontSize: 12, color: T.text, marginBottom: 4 }}>
            <b>Q{i + 1}:</b> {String(q.question || "")}
          </div>
        ))}
      </div>
    );
  }

  // reflect_op / repair_op — show the patch action
  if ((node === "reflect_op_node" || node === "repair_op_node") && parsed) {
    const action = (parsed as Record<string, unknown>).action as string | undefined;
    const reason = (parsed as Record<string, unknown>).reason as string | undefined;
    return (
      <div style={{
        marginTop: 6,
        padding: 10,
        background: T.warningSoft,
        border: `1px solid ${T.warning}55`,
        borderRadius: T.radiusSm,
      }}>
        <div style={{ fontSize: 11, color: T.warning, fontWeight: 600, marginBottom: 6, letterSpacing: 0.3 }}>
          🔧 MODEL DECISION · {action || "patch"}
        </div>
        {reason && (
          <div style={{ fontSize: 12, color: T.text, fontStyle: "italic" }}>
            {reason}
          </div>
        )}
      </div>
    );
  }

  return null;
}

function OpRow({ op }: { op: Record<string, unknown> }) {
  const type = String(op.type || "?");
  const colorByType: Record<string, string> = {
    add_node: T.success,
    connect: T.accent,
    set_param: T.warning,
    remove_node: T.danger,
    run_preview: T.neutral,
  };
  const color = colorByType[type] ?? T.neutral;
  return (
    <div style={{
      padding: "6px 8px",
      marginTop: 4,
      background: "#fff",
      border: `1px solid ${color}33`,
      borderLeft: `3px solid ${color}`,
      borderRadius: T.radiusSm,
      fontSize: 12,
      fontFamily: T.fontMono,
      color: T.text,
    }}>
      <span style={{ color, fontWeight: 600 }}>{type}</span>
      {op.node_id && <span> · <span style={{ color: T.textMuted }}>{String(op.node_id)}</span></span>}
      {op.block_id && <span> · {String(op.block_id)}</span>}
      {type === "connect" && (
        <span> · <span style={{ color: T.accent }}>{String(op.src_id)}</span>.{String(op.src_port || "data")} → <span style={{ color: T.accent }}>{String(op.dst_id)}</span>.{String(op.dst_port || "data")}</span>
      )}
      {op.params != null && Object.keys(op.params as Record<string, unknown>).length > 0 && (
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: "pointer", fontSize: 11, color: T.textMuted, listStyle: "none" }}>
            ▸ params
          </summary>
          <CodeBlock json={op.params} />
        </details>
      )}
    </div>
  );
}

function ResultsTab({ detail, reRun }: { detail: TraceDetail; reRun: ExecuteResult | null }) {
  const dryRunStep = (detail.graph_steps || []).find((s) => s.node === "dry_run");
  const fromTrace = dryRunStep?.node_results;
  const fromReRun = reRun?.node_results;
  const resultsSource: "rerun" | "trace" | null = fromReRun ? "rerun" : fromTrace ? "trace" : null;
  const nodes = detail.final_pipeline?.nodes || [];

  return (
    <div>
      <div style={{
        marginBottom: 16,
        padding: "10px 14px",
        background: resultsSource === "rerun" ? T.accentSoft : (resultsSource === "trace" ? T.successSoft : T.neutralSoft),
        border: `1px solid ${resultsSource === "rerun" ? T.accentBorder : T.border}`,
        borderRadius: T.radius,
        fontSize: 12,
        color: resultsSource === "rerun" ? T.accent : (resultsSource === "trace" ? T.success : T.textMuted),
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}>
        <span>{resultsSource === "rerun" ? "▶" : resultsSource === "trace" ? "📜" : "○"}</span>
        <span>
          {resultsSource === "rerun"
            ? "顯示 re-run 的最新結果"
            : resultsSource === "trace"
              ? "顯示 build 當下 dry-run 的結果"
              : "尚無 runtime 結果。點上方「Re-run pipeline」抓最新資料。"}
        </span>
      </div>
      {nodes.length === 0 && <EmptyState icon="🧩" text="No final pipeline." />}
      {nodes.map((n) => {
        const r = resultsSource === "rerun"
          ? rawToCompact(fromReRun?.[n.id])
          : (fromTrace?.[n.id] as NodeRunResult | undefined);
        return <NodeResultCard key={n.id} node={n} result={r} />;
      })}
    </div>
  );
}

function rawToCompact(raw?: RawNodeResult): NodeRunResult | undefined {
  if (!raw) return undefined;
  const ports: NodeRunResult["ports"] = {};
  for (const [port, blob] of Object.entries(raw.preview || {})) {
    if (!blob || typeof blob !== "object") continue;
    const t = blob.type;
    if (t === "dataframe") {
      const rows = blob.rows || blob.sample_rows || [];
      ports[port] = {
        kind: "dataframe",
        columns: (blob.columns || []).slice(0, 30),
        total: blob.total,
        rows: rows.slice(0, 20),
      };
    } else if (t === "dict") {
      const snap = (blob.snapshot || {}) as Record<string, unknown>;
      const data = snap?.data as unknown;
      if (snap && Object.keys(snap).length > 0) {
        ports[port] = {
          kind: "chart_spec",
          snapshot: snap,
          chart_type: typeof snap.type === "string" ? snap.type : undefined,
          title: typeof snap.title === "string" ? snap.title : undefined,
          n_data_points: Array.isArray(data) ? data.length : null,
        };
      } else {
        ports[port] = { kind: "dict", value: snap };
      }
    } else if (t === "bool") {
      ports[port] = { kind: "bool", value: blob.value };
    } else {
      ports[port] = { kind: t };
    }
  }
  return { status: raw.status, rows: raw.rows, duration_ms: raw.duration_ms, error: raw.error, ports };
}

function NodeResultCard({ node, result }: { node: PipelineNode; result?: NodeRunResult }) {
  const status = result?.status || "(no data)";
  const meta = STATUS_META[status] ?? { color: T.textMuted, bg: T.neutralSoft, label: status };
  return (
    <div style={{
      background: T.bgCard,
      border: `1px solid ${T.border}`,
      borderRadius: T.radius,
      padding: 14,
      marginBottom: 10,
      boxShadow: T.shadowSm,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <NodeChip id={node.id} blockId={node.block_id} />
        <StatusBadge status={status} />
        {result?.rows != null && (
          <span style={{ fontSize: 12, color: T.textMuted, fontFamily: T.fontMono }}>
            {result.rows.toLocaleString()} rows
          </span>
        )}
        {result?.duration_ms != null && (
          <span style={{ fontSize: 12, color: T.textMuted, fontFamily: T.fontMono, marginLeft: "auto" }}>
            ⏱ {fmtDuration(result.duration_ms)}
          </span>
        )}
      </div>
      {result?.error && (
        <div style={{
          background: T.dangerSoft,
          color: T.danger,
          fontSize: 12,
          padding: "8px 12px",
          marginTop: 10,
          borderRadius: T.radiusSm,
          border: `1px solid ${T.danger}33`,
        }}>
          ❌ {result.error}
        </div>
      )}
      {result?.ports && Object.entries(result.ports).map(([port, p]) => (
        <PortCard key={port} port={port} data={p} />
      ))}
    </div>
  );
}

function PortCard({ port, data }: { port: string; data: NonNullable<NodeRunResult["ports"]>[string] }) {
  const kindIcon = data.kind === "dataframe" ? "▦" : data.kind === "chart_spec" ? "📊" : data.kind === "bool" ? "✓" : "·";
  const kindColor = data.kind === "dataframe" ? T.accent : data.kind === "chart_spec" ? T.warning : T.neutral;

  return (
    <div style={{
      marginTop: 10,
      padding: 10,
      background: T.bgSubtle,
      borderRadius: T.radiusSm,
      border: `1px solid ${T.border}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
        <span style={{ color: kindColor, fontSize: 14 }}>{kindIcon}</span>
        <b style={{ color: T.text }}>{port}</b>
        <span style={{
          padding: "1px 6px",
          background: "#fff",
          border: `1px solid ${T.border}`,
          color: T.textMuted,
          fontSize: 10,
          borderRadius: 8,
          fontFamily: T.fontMono,
        }}>{data.kind}</span>
      </div>

      {data.kind === "dataframe" && <DataframePreview data={data} />}
      {data.kind === "chart_spec" && <ChartSpecPreview data={data} />}
      {data.kind === "bool" && (
        <div style={{ marginTop: 6, fontSize: 13, fontFamily: T.fontMono }}>
          <span style={{ color: T.textMuted }}>value:</span>{" "}
          <b style={{ color: data.value ? T.success : T.danger }}>{String(data.value)}</b>
        </div>
      )}
      {data.kind === "dict" && data.keys && (
        <div style={{ marginTop: 6, fontSize: 11, color: T.textMuted, fontFamily: T.fontMono }}>
          keys: {data.keys.join(", ")}
        </div>
      )}
    </div>
  );
}

function DataframePreview({ data }: { data: NonNullable<NodeRunResult["ports"]>[string] }) {
  const rows = data.rows || (data.first_row ? [data.first_row] : []);
  const cols = data.columns || (rows[0] ? Object.keys(rows[0]) : []);
  const showAllCols = cols.slice(0, 8);
  const moreColCount = cols.length - showAllCols.length;
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 11, color: T.textMuted, marginBottom: 6 }}>
        {(data.total ?? rows.length).toLocaleString()} rows · {cols.length} cols
        {rows.length > 0 && rows.length < (data.total ?? 0) && (
          <span> · showing first {rows.length}</span>
        )}
      </div>
      {rows.length > 0 ? (
        <div style={{
          background: "#fff",
          border: `1px solid ${T.border}`,
          borderRadius: T.radiusSm,
          overflow: "auto",
          maxHeight: 320,
        }}>
          <table style={{ borderCollapse: "collapse", fontSize: 11, width: "100%" }}>
            <thead style={{ position: "sticky", top: 0, background: T.bgSubtle, zIndex: 1 }}>
              <tr>
                {showAllCols.map((c) => (
                  <th key={c} style={{
                    padding: "6px 8px",
                    textAlign: "left",
                    borderBottom: `1px solid ${T.border}`,
                    fontFamily: T.fontMono,
                    color: T.textMuted,
                    fontWeight: 600,
                    whiteSpace: "nowrap",
                  }}>{c}</th>
                ))}
                {moreColCount > 0 && (
                  <th style={{
                    padding: "6px 8px",
                    color: T.textSubtle,
                    fontStyle: "italic",
                    fontWeight: 400,
                  }}>+{moreColCount} more</th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} style={{
                  background: i % 2 === 0 ? "#fff" : T.bgSubtle,
                }}>
                  {showAllCols.map((c) => (
                    <td key={c} style={{
                      padding: "5px 8px",
                      borderBottom: `1px solid ${T.border}`,
                      fontFamily: T.fontMono,
                      color: T.text,
                      whiteSpace: "nowrap",
                      maxWidth: 220,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}>{fmtCell(row[c])}</td>
                  ))}
                  {moreColCount > 0 && <td style={{ borderBottom: `1px solid ${T.border}` }}></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ color: T.textSubtle, fontSize: 12, fontStyle: "italic" }}>(no rows)</div>
      )}
    </div>
  );
}

function fmtCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return Math.abs(v) < 0.001 || Math.abs(v) >= 10000 ? v.toExponential(3) : v.toFixed(3);
  }
  if (typeof v === "string") {
    // ISO datetime → trim
    if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 19).replace("T", " ");
    return v.length > 60 ? v.slice(0, 60) + "…" : v;
  }
  if (Array.isArray(v) || typeof v === "object") {
    const s = JSON.stringify(v);
    return s.length > 60 ? s.slice(0, 60) + "…" : s;
  }
  return String(v);
}

function ChartSpecPreview({ data }: { data: NonNullable<NodeRunResult["ports"]>[string] }) {
  const snapshot = data.snapshot;
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{
          padding: "2px 8px",
          background: T.warningSoft,
          color: T.warning,
          borderRadius: 8,
          fontSize: 11,
          fontFamily: T.fontMono,
          fontWeight: 600,
        }}>
          {data.chart_type ?? (snapshot?.type as string) ?? "chart"}
        </span>
        <span style={{ color: T.textMuted, fontSize: 11 }}>
          {data.n_data_points ?? 0} data points
        </span>
        {data.title && (
          <span style={{ color: T.text, fontSize: 12, fontStyle: "italic" }}>
            &ldquo;{data.title}&rdquo;
          </span>
        )}
      </div>
      {snapshot ? (
        <div style={{
          background: "#fff",
          border: `1px solid ${T.border}`,
          borderRadius: T.radiusSm,
          padding: 8,
          minHeight: 120,
        }}>
          <ChartRenderer spec={snapshot} />
        </div>
      ) : (
        <div style={{ color: T.textSubtle, fontSize: 11, fontStyle: "italic" }}>
          (no chart spec — older trace; click Re-run to generate)
        </div>
      )}
      {snapshot && (
        <Collapsible label="raw chart_spec" small>
          <CodeBlock json={snapshot} />
        </Collapsible>
      )}
    </div>
  );
}

// ============================================================================
// Pipeline tab
// ============================================================================

function PipelineTab({ detail }: { detail: TraceDetail }) {
  const fp = detail.final_pipeline || {};
  const nodes = fp.nodes || [];
  const edges = fp.edges || [];
  if (nodes.length === 0) return <EmptyState icon="🧩" text="No pipeline produced." />;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div>
        <SectionTitle icon="⬡" label={`Nodes (${nodes.length})`} />
        {nodes.map((n) => (
          <div key={n.id} style={{
            background: T.bgCard,
            border: `1px solid ${T.border}`,
            borderRadius: T.radius,
            padding: 12,
            marginBottom: 8,
            boxShadow: T.shadowSm,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <NodeChip id={n.id} blockId={n.block_id} />
            </div>
            {n.params && Object.keys(n.params).length > 0 && (
              <Collapsible label={`params (${Object.keys(n.params).length})`} small defaultOpen>
                <CodeBlock json={n.params} />
              </Collapsible>
            )}
          </div>
        ))}
      </div>
      <div>
        <SectionTitle icon="↦" label={`Edges (${edges.length})`} />
        <div style={{
          background: T.bgCard,
          border: `1px solid ${T.border}`,
          borderRadius: T.radius,
          padding: 12,
          fontFamily: T.fontMono,
          fontSize: 12,
          boxShadow: T.shadowSm,
        }}>
          {edges.length === 0 && <span style={{ color: T.textSubtle }}>(no edges)</span>}
          {edges.map((e, i) => (
            <div key={i} style={{
              padding: "6px 10px",
              background: i % 2 === 0 ? T.bgSubtle : "transparent",
              borderRadius: T.radiusSm,
              color: T.text,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}>
              <span style={{ color: T.accent }}>{e.from?.node}</span>
              <span style={{ color: T.textSubtle }}>.{e.from?.port}</span>
              <span style={{ color: T.textMuted, margin: "0 4px" }}>→</span>
              <span style={{ color: T.accent }}>{e.to?.node}</span>
              <span style={{ color: T.textSubtle }}>.{e.to?.port}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Shared bits
// ============================================================================

function NodeChip({ id, blockId }: { id: string; blockId: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{
        padding: "2px 8px",
        background: T.text,
        color: "#fff",
        borderRadius: 4,
        fontSize: 11,
        fontFamily: T.fontMono,
        fontWeight: 700,
      }}>{id}</span>
      <span style={{ fontSize: 12, color: T.textMuted, fontFamily: T.fontMono }}>{blockId}</span>
    </span>
  );
}

function SectionTitle({ icon, label }: { icon: string; label: string }) {
  return (
    <h3 style={{
      margin: "0 0 10px",
      fontSize: 13,
      fontWeight: 600,
      color: T.textMuted,
      textTransform: "uppercase",
      letterSpacing: 0.5,
      display: "flex",
      alignItems: "center",
      gap: 6,
    }}>
      <span>{icon}</span>{label}
    </h3>
  );
}

function Collapsible({ label, children, defaultOpen, color, small }: {
  label: string; children: React.ReactNode; defaultOpen?: boolean; color?: string; small?: boolean;
}) {
  return (
    <details open={defaultOpen} style={{ marginTop: small ? 4 : 6 }}>
      <summary style={{
        cursor: "pointer",
        fontSize: small ? 11 : 12,
        color: color ?? T.textMuted,
        padding: "3px 0",
        fontFamily: T.font,
        userSelect: "none",
        listStyle: "none",
      }}>
        ▸ {label}
      </summary>
      <div style={{ marginTop: 4 }}>{children}</div>
    </details>
  );
}

function CodeBlock({ json, text }: { json?: unknown; text?: string }) {
  const content = json !== undefined ? JSON.stringify(json, null, 2) : (text ?? "");
  return (
    <pre style={{
      whiteSpace: "pre-wrap",
      wordWrap: "break-word",
      fontSize: 11,
      lineHeight: 1.5,
      background: T.bgCode,
      color: T.textInverse,
      padding: 12,
      borderRadius: T.radiusSm,
      maxHeight: 320,
      overflow: "auto",
      margin: "4px 0",
      fontFamily: T.fontMono,
    }}>{content}</pre>
  );
}

function EmptyState({ icon, text }: { icon: string; text: string }) {
  return (
    <div style={{
      padding: 48,
      textAlign: "center",
      color: T.textSubtle,
      fontSize: 13,
      background: T.bgCard,
      border: `1px dashed ${T.border}`,
      borderRadius: T.radius,
    }}>
      <div style={{ fontSize: 36, marginBottom: 8 }}>{icon}</div>
      {text}
    </div>
  );
}
