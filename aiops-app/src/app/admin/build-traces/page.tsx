"use client";

import { useEffect, useMemo, useState } from "react";

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
    columns?: string[];
    total?: number;
    first_row?: Record<string, unknown> | null;
    chart_type?: string;
    title?: string;
    n_data_points?: number | null;
    keys?: string[];
    value?: unknown;
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

const STATUS_COLORS: Record<string, string> = {
  finished: "#3fb950",
  plan_unfixable: "#f85149",
  failed: "#f85149",
  failed_structural: "#f85149",
  needs_confirm: "#d29922",
  cancelled: "#8b949e",
  ok: "#3fb950",
  success: "#3fb950",
  partial: "#d29922",
  error: "#f85149",
  skipped: "#8b949e",
};

function fmtTime(iso?: string): string {
  if (!iso) return "";
  return iso.replace("T", " ").slice(0, 19);
}
function fmtTimeShort(iso?: string): string {
  if (!iso) return "";
  // Returns HH:MM:SS.mmm
  const m = iso.match(/T(\d{2}:\d{2}:\d{2})(\.\d{3})?/);
  return m ? m[1] + (m[2] ?? "") : iso;
}
function fmtDuration(ms?: number): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export default function BuildTracesPage() {
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [traceDir, setTraceDir] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("");
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

  const filtered = statusFilter ? traces.filter((t) => t.status === statusFilter) : traces;
  const statusCounts = traces.reduce<Record<string, number>>((acc, t) => {
    const s = t.status || "(none)";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <div style={{ display: "flex", height: "calc(100vh - 64px)", margin: -32 }}>
      <div style={{ width: "38%", overflowY: "auto", borderRight: "1px solid #e2e8f0", padding: 16 }}>
        <h2 style={{ marginTop: 0 }}>
          Build Traces
          <span style={{ fontSize: 12, color: "#718096", marginLeft: 12 }}>
            {traceDir} · {filtered.length}/{traces.length}
          </span>
        </h2>

        <div style={{ marginBottom: 12 }}>
          <FilterPill label={`all (${traces.length})`} active={statusFilter === ""} onClick={() => setStatusFilter("")} />
          {Object.entries(statusCounts).map(([s, n]) => (
            <FilterPill key={s} label={`${s} (${n})`} active={statusFilter === s} color={STATUS_COLORS[s]} onClick={() => setStatusFilter(s)} />
          ))}
        </div>

        {error && <div style={{ color: "#f85149", marginBottom: 12 }}>Error: {error}</div>}
        {loading && <div>Loading…</div>}
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#f7fafc" }}>
              <th style={th}>Started</th>
              <th style={th}>Status</th>
              <th style={{ ...th, textAlign: "right" }}>Dur</th>
              <th style={{ ...th, textAlign: "right" }}>S/L</th>
              <th style={{ ...th, textAlign: "right" }}>N/E</th>
              <th style={th}>Instruction</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <tr
                key={t.file}
                onClick={() => loadDetail(t.file)}
                style={{
                  borderBottom: "1px solid #edf2f7",
                  cursor: "pointer",
                  background: selectedFile === t.file ? "#ebf8ff" : "transparent",
                }}
              >
                <td style={td}>{fmtTime(t.started_at)}</td>
                <td style={{ ...td, color: STATUS_COLORS[t.status || ""] || "#1a202c", fontWeight: 600 }}>{t.status || "-"}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtDuration(t.duration_ms)}</td>
                <td style={{ ...td, textAlign: "right" }}>{t.n_steps}/{t.n_llm}</td>
                <td style={{ ...td, textAlign: "right" }}>{t.n_nodes}/{t.n_edges}</td>
                <td style={{ ...td, fontSize: 11, color: "#4a5568", whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>{t.instruction}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 16, background: "#f7fafc" }}>
        {!selectedFile && <div style={{ color: "#718096" }}>Select a trace on the left to inspect.</div>}
        {detailLoading && <div>Loading trace…</div>}
        {detail && (
          <DetailHeader detail={detail} tab={tab} setTab={setTab} onReRun={reRunPipeline} reRunLoading={reRunLoading} reRun={reRun} />
        )}
        {detail && tab === "journey" && <JourneyTab detail={detail} />}
        {detail && tab === "results" && <ResultsTab detail={detail} reRun={reRun} />}
        {detail && tab === "pipeline" && <PipelineTab detail={detail} />}
      </div>
    </div>
  );
}

function FilterPill({ label, active, color, onClick }: { label: string; active: boolean; color?: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 10px",
        marginRight: 4,
        marginBottom: 4,
        border: "1px solid #cbd5e0",
        background: active ? (color || "#2d3748") : "#fff",
        color: active ? "#fff" : (color || "#1a202c"),
        borderRadius: 4,
        cursor: "pointer",
        fontSize: 12,
      }}
    >
      {label}
    </button>
  );
}

function DetailHeader({
  detail, tab, setTab, onReRun, reRunLoading, reRun,
}: {
  detail: TraceDetail; tab: string; setTab: (t: "journey" | "results" | "pipeline") => void;
  onReRun: () => void; reRunLoading: boolean; reRun: ExecuteResult | null;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <h3 style={{ margin: "0 0 4px" }}>
        <span style={{ color: STATUS_COLORS[detail.status || ""] || "inherit" }}>{detail.status}</span>{" "}
        <span style={{ fontFamily: "monospace", fontSize: 12, color: "#718096" }}>{detail.build_id}</span>{" "}
        <span style={{ fontSize: 12, color: "#718096" }}>· {fmtDuration(detail.duration_ms)}</span>
      </h3>
      <div style={{ fontSize: 12, color: "#4a5568", marginBottom: 8 }}>{detail.instruction}</div>
      <div>
        {(["journey", "results", "pipeline"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "6px 14px",
              marginRight: 4,
              border: "1px solid #cbd5e0",
              borderBottom: tab === t ? "1px solid #3182ce" : "1px solid #cbd5e0",
              background: tab === t ? "#ebf8ff" : "#fff",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            {t === "journey" ? "📜 Journey" : t === "results" ? "📊 Results" : "🧩 Pipeline"}
          </button>
        ))}
        <button
          onClick={onReRun}
          disabled={reRunLoading || !detail.final_pipeline}
          style={{
            padding: "6px 14px",
            marginLeft: 12,
            border: "1px solid #3182ce",
            background: reRunLoading ? "#bee3f8" : "#3182ce",
            color: "#fff",
            cursor: reRunLoading ? "wait" : "pointer",
            fontSize: 13,
            borderRadius: 4,
          }}
        >
          {reRunLoading ? "Running…" : "▶ Re-run pipeline"}
        </button>
        {reRun && reRun.status && (
          <span style={{ marginLeft: 12, fontSize: 12, color: STATUS_COLORS[reRun.status] || "#1a202c" }}>
            re-run: {reRun.status} · {fmtDuration(reRun.duration_ms)}
            {reRun.error_message && ` · ${reRun.error_message.slice(0, 80)}`}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Journey: chronological timeline of EVERY event ──────────────────
function JourneyTab({ detail }: { detail: TraceDetail }) {
  // Merge graph_steps + llm_calls into one timeline sorted by ts.
  type Item = { ts?: string; kind: "step" | "llm"; data: GraphStep | LlmCall };
  const items: Item[] = useMemo(() => {
    const out: Item[] = [];
    for (const s of detail.graph_steps || []) out.push({ ts: s.ts, kind: "step", data: s });
    for (const c of detail.llm_calls || []) out.push({ ts: c.ts, kind: "llm", data: c });
    out.sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
    return out;
  }, [detail]);

  return (
    <div>
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
  return (
    <div style={{
      borderLeft: `3px solid ${failed ? "#f85149" : isLlm ? "#a78bfa" : "#3fb950"}`,
      background: "#fff",
      padding: 10,
      margin: "6px 0",
      borderRadius: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        <span style={{ fontFamily: "monospace", color: "#718096" }}>{fmtTimeShort(item.ts)}</span>
        <span style={{
          padding: "1px 8px",
          background: isLlm ? "#ede9fe" : "#dcfce7",
          color: isLlm ? "#6b21a8" : "#166534",
          borderRadius: 3,
          fontSize: 11,
          fontWeight: 600,
        }}>{isLlm ? "LLM" : "STEP"}</span>
        <b style={{ fontSize: 13 }}>{node}</b>
        {(data as GraphStep).step_idx != null && (
          <span style={{ color: "#718096", fontSize: 12 }}>step_{(data as GraphStep).step_idx}</span>
        )}
        {(data as LlmCall).attempt != null && (
          <span style={{ color: "#d29922", fontSize: 12 }}>attempt {(data as LlmCall).attempt}</span>
        )}
        {(data as GraphStep).duration_ms != null && (
          <span style={{ color: "#718096", fontSize: 12 }}>{(data as GraphStep).duration_ms}ms</span>
        )}
      </div>
      {(data as GraphStep).step_text && (
        <div style={{ fontSize: 12, color: "#2c5282", marginTop: 4 }}>📋 {(data as GraphStep).step_text}</div>
      )}
      {(data as GraphStep).autofixes && ((data as GraphStep).autofixes as string[]).length > 0 && (
        <div style={{ marginTop: 4 }}>
          {((data as GraphStep).autofixes as string[]).map((n: string, i: number) => (
            <div key={i} style={{ fontSize: 11, color: "#7c2d12", marginTop: 2 }}>⚙ {n}</div>
          ))}
        </div>
      )}
      {(data as GraphStep).ops_emitted && (
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: "pointer", fontSize: 12, color: "#718096" }}>
            ops emitted ({((data as GraphStep).ops_emitted as Array<unknown>).length})
          </summary>
          <pre style={preStyle}>{JSON.stringify((data as GraphStep).ops_emitted, null, 2)}</pre>
        </details>
      )}
      {(data as GraphStep).node_results && (
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: "pointer", fontSize: 12, color: "#2c5282", fontWeight: 600 }}>
            🎯 dry-run results
          </summary>
          <pre style={preStyle}>{JSON.stringify((data as GraphStep).node_results, null, 2)}</pre>
        </details>
      )}
      {isLlm && (
        <div style={{ marginTop: 6 }}>
          <details>
            <summary style={{ cursor: "pointer", fontSize: 12, color: "#6b21a8" }}>
              user_msg ({((data as LlmCall).user_msg || "").length} chars)
            </summary>
            <pre style={preStyle}>{(data as LlmCall).user_msg || ""}</pre>
          </details>
          <details>
            <summary style={{ cursor: "pointer", fontSize: 12, color: "#6b21a8" }}>raw_response</summary>
            <pre style={preStyle}>{(data as LlmCall).raw_response || ""}</pre>
          </details>
          {(data as LlmCall).parsed != null && (
            <details>
              <summary style={{ cursor: "pointer", fontSize: 12, color: "#6b21a8" }}>parsed</summary>
              <pre style={preStyle}>{JSON.stringify((data as LlmCall).parsed, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

// ── Results: per-node runtime data ───────────────────────────────────
function ResultsTab({ detail, reRun }: { detail: TraceDetail; reRun: ExecuteResult | null }) {
  // Use re-run if present, else dig dry-run from graph_steps
  const dryRunStep = (detail.graph_steps || []).find((s) => s.node === "dry_run");
  const fromTrace = dryRunStep?.node_results;
  const fromReRun = reRun?.node_results;

  // Pick re-run if available
  const resultsSource: "rerun" | "trace" | null = fromReRun ? "rerun" : fromTrace ? "trace" : null;
  const nodes = detail.final_pipeline?.nodes || [];

  return (
    <div>
      <div style={{ marginBottom: 12, padding: 8, background: "#fff", borderRadius: 4, fontSize: 12, color: "#4a5568" }}>
        資料來源：{resultsSource === "rerun" ? "▶ 剛剛 re-run 的結果" : resultsSource === "trace" ? "📜 build 當下 dry-run 的結果" : "(無 — 點上方「Re-run pipeline」抓"}
      </div>
      {nodes.map((n) => {
        const r = resultsSource === "rerun"
          ? rawToCompact(fromReRun?.[n.id])
          : (fromTrace?.[n.id] as NodeRunResult | undefined);
        return <NodeResultCard key={n.id} node={n} result={r} />;
      })}
    </div>
  );
}

// Convert raw executor preview shape → compact NodeRunResult
function rawToCompact(raw?: RawNodeResult): NodeRunResult | undefined {
  if (!raw) return undefined;
  const ports: NodeRunResult["ports"] = {};
  for (const [port, blob] of Object.entries(raw.preview || {})) {
    if (!blob || typeof blob !== "object") continue;
    const t = blob.type;
    if (t === "dataframe") {
      const rows = blob.rows || blob.sample_rows || [];
      ports[port] = { kind: "dataframe", columns: (blob.columns || []).slice(0, 20), total: blob.total, first_row: rows[0] || null };
    } else if (t === "dict") {
      const snap = blob.snapshot || {};
      const data = snap.data;
      if (Array.isArray(data)) {
        ports[port] = { kind: "chart_spec", chart_type: snap.type, title: snap.title, n_data_points: data.length };
      } else {
        ports[port] = { kind: "dict", keys: Object.keys(snap || {}).slice(0, 10) };
      }
    } else if (t === "bool") {
      ports[port] = { kind: "bool", value: blob.value };
    } else {
      ports[port] = { kind: t };
    }
  }
  return {
    status: raw.status,
    rows: raw.rows,
    duration_ms: raw.duration_ms,
    error: raw.error,
    ports,
  };
}

function NodeResultCard({ node, result }: { node: PipelineNode; result?: NodeRunResult }) {
  const status = result?.status || "(no data)";
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 4, padding: 12, marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <b>{node.id}</b>
        <span style={{ fontSize: 12, color: "#4a5568" }}>[{node.block_id}]</span>
        <span style={{
          marginLeft: "auto",
          padding: "2px 8px",
          background: STATUS_COLORS[status] || "#e2e8f0",
          color: "#fff",
          fontSize: 11,
          borderRadius: 3,
        }}>{status}</span>
        {result?.rows != null && (
          <span style={{ fontSize: 12, color: "#718096" }}>{result.rows} rows</span>
        )}
        {result?.duration_ms != null && (
          <span style={{ fontSize: 12, color: "#718096" }}>{result.duration_ms.toFixed(1)}ms</span>
        )}
      </div>
      {result?.error && (
        <div style={{ background: "#fee2e2", color: "#7f1d1d", fontSize: 12, padding: 6, marginTop: 6, borderRadius: 3 }}>
          ❌ {result.error}
        </div>
      )}
      {result?.ports && Object.entries(result.ports).map(([port, p]) => (
        <div key={port} style={{ marginTop: 6, fontSize: 12 }}>
          <b>port: {port}</b> <span style={{ color: "#718096" }}>({p.kind})</span>
          {p.kind === "dataframe" && (
            <div style={{ marginTop: 4 }}>
              <div style={{ color: "#4a5568" }}>{p.total} rows · cols: {(p.columns || []).join(", ")}</div>
              {p.first_row && (
                <details>
                  <summary style={{ cursor: "pointer", color: "#718096" }}>first row</summary>
                  <pre style={preStyle}>{JSON.stringify(p.first_row, null, 2)}</pre>
                </details>
              )}
            </div>
          )}
          {p.kind === "chart_spec" && (
            <div style={{ marginTop: 4, color: "#4a5568" }}>
              📊 {p.chart_type} · {p.n_data_points} pts · {p.title || "(no title)"}
            </div>
          )}
          {p.kind === "bool" && (
            <div style={{ marginTop: 4 }}>value = <b>{String(p.value)}</b></div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Pipeline: structural view ────────────────────────────────────────
function PipelineTab({ detail }: { detail: TraceDetail }) {
  const fp = detail.final_pipeline || {};
  return (
    <div>
      <h4 style={{ margin: "0 0 8px" }}>
        Final Pipeline ({(fp.nodes || []).length} nodes, {(fp.edges || []).length} edges)
      </h4>
      {(fp.nodes || []).map((n) => (
        <div key={n.id} style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 4, padding: 10, marginBottom: 6, fontSize: 12 }}>
          <b>{n.id}</b> [{n.block_id}]
          <pre style={preStyle}>{JSON.stringify(n.params || {}, null, 2)}</pre>
        </div>
      ))}
      <h4 style={{ margin: "16px 0 8px" }}>Edges</h4>
      {(fp.edges || []).map((e, i) => (
        <div key={i} style={{ fontFamily: "monospace", fontSize: 12, padding: 4, color: "#4a5568" }}>
          {e.from?.node}.{e.from?.port} → {e.to?.node}.{e.to?.port}
        </div>
      ))}
    </div>
  );
}

const th: React.CSSProperties = { padding: 6, textAlign: "left", fontSize: 11, color: "#4a5568", borderBottom: "1px solid #e2e8f0" };
const td: React.CSSProperties = { padding: 6, fontSize: 12 };
const preStyle: React.CSSProperties = {
  whiteSpace: "pre-wrap",
  wordWrap: "break-word",
  fontSize: 11,
  background: "#1a202c",
  color: "#e2e8f0",
  padding: 8,
  borderRadius: 4,
  maxHeight: 300,
  overflow: "auto",
  margin: "4px 0",
};
