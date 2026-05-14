"use client";

import { useEffect, useState } from "react";

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

type GraphStep = Record<string, unknown> & { node?: string; ts?: string; status?: string; duration_ms?: number };
type LlmCall = Record<string, unknown> & { node?: string; ts?: string; attempt?: number; user_msg?: string; raw_response?: string; parsed?: unknown };
type Node = { id: string; block_id: string; params?: Record<string, unknown> };

interface TraceDetail {
  build_id?: string;
  session_id?: string;
  status?: string;
  duration_ms?: number;
  instruction?: string;
  graph_steps?: GraphStep[];
  llm_calls?: LlmCall[];
  final_pipeline?: { nodes?: Node[]; edges?: unknown[] };
}

const STATUS_COLORS: Record<string, string> = {
  finished: "#3fb950",
  plan_unfixable: "#f85149",
  failed: "#f85149",
  failed_structural: "#f85149",
  needs_confirm: "#d29922",
  cancelled: "#8b949e",
};

function fmtTime(iso?: string): string {
  if (!iso) return "";
  try {
    return iso.replace("T", " ").slice(0, 19);
  } catch {
    return iso;
  }
}

function fmtDuration(ms?: number): string {
  if (!ms && ms !== 0) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
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

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    fetch("/api/admin/build-traces")
      .then((r) => r.json())
      .then((data) => {
        if (!mounted) return;
        if (data.error) {
          setError(data.error);
        } else {
          setTraces(data.traces || []);
          setTraceDir(data.dir || "");
        }
      })
      .catch((e) => mounted && setError(String(e)))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  function loadDetail(file: string) {
    setSelectedFile(file);
    setDetailLoading(true);
    setDetail(null);
    fetch(`/api/admin/build-traces/${encodeURIComponent(file)}`)
      .then((r) => r.json())
      .then((data) => setDetail(data))
      .catch((e) => setDetail({ status: "fetch error: " + String(e) }))
      .finally(() => setDetailLoading(false));
  }

  const filtered = statusFilter
    ? traces.filter((t) => t.status === statusFilter)
    : traces;
  const statusCounts = traces.reduce<Record<string, number>>((acc, t) => {
    const s = t.status || "(none)";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <div style={{ display: "flex", height: "calc(100vh - 64px)", margin: -32 }}>
      {/* Left list */}
      <div style={{ width: "45%", overflowY: "auto", borderRight: "1px solid #e2e8f0", padding: 16 }}>
        <h2 style={{ marginTop: 0 }}>
          Build Traces
          <span style={{ fontSize: 12, color: "#718096", marginLeft: 12 }}>
            {traceDir} · {filtered.length}/{traces.length}
          </span>
        </h2>

        <div style={{ marginBottom: 12, fontSize: 12 }}>
          <button
            onClick={() => setStatusFilter("")}
            style={{
              padding: "4px 10px",
              marginRight: 4,
              border: "1px solid #cbd5e0",
              background: statusFilter === "" ? "#2d3748" : "#fff",
              color: statusFilter === "" ? "#fff" : "#1a202c",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            all ({traces.length})
          </button>
          {Object.entries(statusCounts).map(([s, n]) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              style={{
                padding: "4px 10px",
                marginRight: 4,
                border: "1px solid #cbd5e0",
                background: statusFilter === s ? STATUS_COLORS[s] || "#2d3748" : "#fff",
                color: statusFilter === s ? "#fff" : STATUS_COLORS[s] || "#1a202c",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              {s} ({n})
            </button>
          ))}
        </div>

        {error && <div style={{ color: "#f85149", marginBottom: 12 }}>Error: {error}</div>}
        {loading && <div>Loading…</div>}
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#f7fafc" }}>
              <th style={{ padding: 6, textAlign: "left" }}>Started</th>
              <th style={{ padding: 6, textAlign: "left" }}>Status</th>
              <th style={{ padding: 6, textAlign: "right" }}>Dur</th>
              <th style={{ padding: 6, textAlign: "right" }}>Steps/LLM</th>
              <th style={{ padding: 6, textAlign: "right" }}>N/E</th>
              <th style={{ padding: 6, textAlign: "left" }}>Instruction</th>
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
                <td style={{ padding: 6 }}>{fmtTime(t.started_at)}</td>
                <td style={{ padding: 6, color: STATUS_COLORS[t.status || ""] || "#1a202c" }}>
                  {t.status || "-"}
                </td>
                <td style={{ padding: 6, textAlign: "right" }}>{fmtDuration(t.duration_ms)}</td>
                <td style={{ padding: 6, textAlign: "right" }}>{t.n_steps}/{t.n_llm}</td>
                <td style={{ padding: 6, textAlign: "right" }}>{t.n_nodes}/{t.n_edges}</td>
                <td style={{ padding: 6, fontSize: 11, color: "#4a5568" }}>{t.instruction}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Right detail */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16, background: "#f7fafc" }}>
        {!selectedFile && <div style={{ color: "#718096" }}>Select a trace on the left.</div>}
        {detailLoading && <div>Loading trace…</div>}
        {detail && <DetailPanel detail={detail} />}
      </div>
    </div>
  );
}

function DetailPanel({ detail }: { detail: TraceDetail }) {
  return (
    <div style={{ fontSize: 12 }}>
      <h3 style={{ marginTop: 0 }}>
        {detail.build_id} <span style={{ color: STATUS_COLORS[detail.status || ""] || "inherit" }}>{detail.status}</span>{" "}
        <span style={{ color: "#718096", fontWeight: "normal" }}>{fmtDuration(detail.duration_ms)} · {detail.session_id}</span>
      </h3>

      <Section title="Instruction">
        <pre style={preStyle}>{detail.instruction || ""}</pre>
      </Section>

      <Section title={`Final Pipeline (${detail.final_pipeline?.nodes?.length || 0} nodes, ${detail.final_pipeline?.edges?.length || 0} edges)`}>
        {(detail.final_pipeline?.nodes || []).map((n) => (
          <div key={n.id} style={stepStyle}>
            <b>{n.id}</b> [{n.block_id}]
            <pre style={preStyle}>{JSON.stringify(n.params || {}, null, 2)}</pre>
          </div>
        ))}
      </Section>

      <Section title={`Graph Steps (${detail.graph_steps?.length || 0})`}>
        {(detail.graph_steps || []).map((s, i) => (
          <div key={i} style={{ ...stepStyle, borderLeft: `3px solid ${s.status === "failed" ? "#f85149" : s.status === "ok" ? "#3fb950" : "#cbd5e0"}` }}>
            <b>{s.node || "?"}</b>{" "}
            <span style={{ color: "#718096" }}>{s.ts || ""}</span>
            {typeof s.duration_ms === "number" && <span style={{ color: "#718096", marginLeft: 8 }}>{s.duration_ms}ms</span>}
            <details>
              <summary style={{ cursor: "pointer" }}>fields</summary>
              <pre style={preStyle}>{JSON.stringify(s, null, 2)}</pre>
            </details>
          </div>
        ))}
      </Section>

      <Section title={`LLM Calls (${detail.llm_calls?.length || 0})`}>
        {(detail.llm_calls || []).map((c, i) => (
          <div key={i} style={stepStyle}>
            <b>{c.node || "?"}</b>
            {typeof c.attempt === "number" && <span style={tagStyle}>attempt {c.attempt}</span>}
            <span style={{ color: "#718096", marginLeft: 8 }}>{c.ts || ""}</span>
            <details>
              <summary style={{ cursor: "pointer" }}>user_msg ({(c.user_msg || "").length} chars)</summary>
              <pre style={preStyle}>{c.user_msg || ""}</pre>
            </details>
            <details>
              <summary style={{ cursor: "pointer" }}>raw_response</summary>
              <pre style={preStyle}>{c.raw_response || ""}</pre>
            </details>
            {c.parsed != null && (
              <details>
                <summary style={{ cursor: "pointer" }}>parsed</summary>
                <pre style={preStyle}>{JSON.stringify(c.parsed, null, 2)}</pre>
              </details>
            )}
          </div>
        ))}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 6, padding: 12 }}>
      <h4 style={{ margin: "0 0 8px", color: "#2c5282", fontSize: 13 }}>{title}</h4>
      {children}
    </div>
  );
}

const stepStyle: React.CSSProperties = {
  padding: "6px 10px",
  background: "#f7fafc",
  margin: "4px 0",
  borderRadius: 4,
  borderLeft: "3px solid #cbd5e0",
};

const preStyle: React.CSSProperties = {
  whiteSpace: "pre-wrap",
  wordWrap: "break-word",
  fontSize: 11,
  background: "#1a202c",
  color: "#e2e8f0",
  padding: 8,
  borderRadius: 4,
  maxHeight: 400,
  overflow: "auto",
  margin: "4px 0",
};

const tagStyle: React.CSSProperties = {
  marginLeft: 8,
  padding: "1px 6px",
  background: "#e2e8f0",
  fontSize: 11,
  borderRadius: 3,
};
