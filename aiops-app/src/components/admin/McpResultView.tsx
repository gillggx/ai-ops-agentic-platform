"use client";

/**
 * McpResultView — readable rendering of a System MCP sample-fetch response.
 *
 * Replaces the raw JSON <pre> dump on the admin page. Detects the response
 * shape and renders accordingly:
 *   - array of objects            → table (columns = union of keys)
 *   - object holding a data array  → table on that array + a small meta row
 *   - plain object                → key/value list (nested values pretty-printed)
 *   - array of scalars            → list
 *   - error / unparseable          → error card
 * A "表格 / JSON" toggle keeps the raw view one click away. Built to fill the
 * available height so the admin full-page layout can use it as the data pane.
 */

import { useMemo, useState } from "react";

interface Props {
  result: unknown;        // parsed response object (not a string)
  loading?: boolean;
  error?: string | null;
  latencyMs?: number | null;
}

const ARRAY_KEYS = ["events", "data", "items", "results", "rows", "records", "list"];

/** Find the primary array-of-objects to tabulate, plus the rest of the envelope. */
function findTable(result: unknown): { rows: Record<string, unknown>[]; sourceKey: string | null; envelope: Record<string, unknown> | null } {
  if (Array.isArray(result) && result.every(r => r && typeof r === "object" && !Array.isArray(r))) {
    return { rows: result as Record<string, unknown>[], sourceKey: null, envelope: null };
  }
  if (result && typeof result === "object" && !Array.isArray(result)) {
    const obj = result as Record<string, unknown>;
    for (const k of ARRAY_KEYS) {
      const v = obj[k];
      if (Array.isArray(v) && v.length > 0 && v.every(r => r && typeof r === "object" && !Array.isArray(r))) {
        return { rows: v as Record<string, unknown>[], sourceKey: k, envelope: obj };
      }
    }
    // any array-of-objects field
    for (const [k, v] of Object.entries(obj)) {
      if (Array.isArray(v) && v.length > 0 && v.every(r => r && typeof r === "object" && !Array.isArray(r))) {
        return { rows: v as Record<string, unknown>[], sourceKey: k, envelope: obj };
      }
    }
  }
  return { rows: [], sourceKey: null, envelope: null };
}

const MAX_ROWS = 200;

function cellColor(v: unknown): string | undefined {
  const s = String(v).toUpperCase();
  if (s === "OOC" || s === "FAIL" || s === "FAULT" || s === "NG" || s === "ALARM") return "#c53030";
  if (s === "PASS" || s === "OK" || s === "NORMAL" || s === "GOOD") return "#2f855a";
  if (s === "WARNING" || s === "WARN" || s === "HOLD") return "#b7791f";
  return undefined;
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, "");
  return String(v);
}

export default function McpResultView({ result, loading, error, latencyMs }: Props) {
  const [view, setView] = useState<"table" | "json">("table");

  const { rows, sourceKey } = useMemo(() => findTable(result), [result]);
  const columns = useMemo(() => {
    const set = new Set<string>();
    rows.slice(0, MAX_ROWS).forEach(r => Object.keys(r).forEach(k => set.add(k)));
    return Array.from(set);
  }, [rows]);

  if (loading) {
    return <Shell><div style={{ color: "#a0aec0", fontSize: 13, padding: 40, textAlign: "center" }}>撈取中…</div></Shell>;
  }
  if (error) {
    return (
      <Shell>
        <div style={{ background: "#fff5f5", border: "1px solid #fed7d7", borderRadius: 8, padding: "14px 16px", color: "#c53030" }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>[no] 呼叫失敗</div>
          <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", fontFamily: "ui-monospace, monospace" }}>{error}</pre>
        </div>
      </Shell>
    );
  }
  if (result === null || result === undefined) {
    return <Shell><div style={{ color: "#a0aec0", fontSize: 13, padding: 40, textAlign: "center" }}>尚未執行 — 填參數後按「執行 Sample Fetch」</div></Shell>;
  }

  const isTable = rows.length > 0;
  const meta = (
    <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 10 }}>
      <Badge tone="ok">200 OK</Badge>
      {isTable && <span style={{ fontSize: 12, color: "#4a5568" }}>{rows.length} 筆{sourceKey ? ` · ${sourceKey}` : ""}{rows.length > MAX_ROWS ? `（顯示前 ${MAX_ROWS}）` : ""}</span>}
      {latencyMs != null && <span style={{ fontSize: 12, color: "#a0aec0" }}>{latencyMs} ms</span>}
      <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
        {(["table", "json"] as const).map(v => (
          <button key={v} onClick={() => setView(v)} style={{
            fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 6, cursor: "pointer",
            border: `1px solid ${view === v ? "#3182ce" : "#e2e8f0"}`,
            background: view === v ? "#ebf8ff" : "#fff", color: view === v ? "#2b6cb0" : "#718096",
          }}>{v === "table" ? "表格" : "JSON"}</button>
        ))}
      </div>
    </div>
  );

  return (
    <Shell>
      {meta}
      {view === "json" || !isTable ? (
        isTable || view === "json" ? (
          <JsonBlock value={result} />
        ) : (
          <ObjectView value={result} />
        )
      ) : (
        <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8, flex: 1, minHeight: 0 }}>
          <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%", whiteSpace: "nowrap" }}>
            <thead>
              <tr style={{ background: "#f7f8fc", position: "sticky", top: 0 }}>
                <th style={thStyle}>#</th>
                {columns.map(c => <th key={c} style={thStyle}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, MAX_ROWS).map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <td style={{ ...tdStyle, color: "#cbd5e0" }}>{i + 1}</td>
                  {columns.map(c => {
                    const raw = r[c];
                    const txt = fmtCell(raw);
                    const color = cellColor(raw);
                    return (
                      <td key={c} style={{ ...tdStyle, color: color ?? "#2d3748", fontWeight: color ? 700 : 400, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }} title={txt}>
                        {txt}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>{children}</div>;
}

function Badge({ tone, children }: { tone: "ok" | "err"; children: React.ReactNode }) {
  const ok = tone === "ok";
  return <span style={{
    fontSize: 11, fontWeight: 700, padding: "2px 9px", borderRadius: 999,
    background: ok ? "#f0fff4" : "#fff5f5", color: ok ? "#2f855a" : "#c53030",
    border: `1px solid ${ok ? "#c6f6d5" : "#fed7d7"}`,
  }}>{children}</span>;
}

function ObjectView({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <JsonBlock value={value} />;
  const entries = Object.entries(value as Record<string, unknown>);
  return (
    <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, padding: "8px 4px", borderBottom: "1px solid #f0f4f8" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#4a5568", fontFamily: "ui-monospace, monospace" }}>{k}</span>
          <span style={{ fontSize: 12, color: cellColor(v) ?? "#2d3748", fontWeight: cellColor(v) ? 700 : 400, wordBreak: "break-word" }}>
            {typeof v === "object" && v !== null ? <JsonBlock value={v} compact /> : fmtCell(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

function JsonBlock({ value, compact }: { value: unknown; compact?: boolean }) {
  return (
    <pre style={{
      background: compact ? "#f7fafc" : "#1a202c", color: compact ? "#2d3748" : "#e2e8f0",
      borderRadius: 8, padding: compact ? 8 : 14, fontSize: 11.5, fontFamily: "ui-monospace, monospace",
      overflow: "auto", margin: 0, lineHeight: 1.6, flex: compact ? undefined : 1, minHeight: 0,
      maxHeight: compact ? 200 : undefined, whiteSpace: "pre-wrap",
    }}>{JSON.stringify(value, null, 2)}</pre>
  );
}

const thStyle: React.CSSProperties = {
  padding: "8px 12px", textAlign: "left", fontWeight: 700, color: "#4a5568",
  borderBottom: "2px solid #e2e8f0", fontSize: 11, whiteSpace: "nowrap",
};
const tdStyle: React.CSSProperties = {
  padding: "6px 12px", borderRight: "1px solid #f7fafc",
};
