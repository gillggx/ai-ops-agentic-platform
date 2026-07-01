"use client";

/**
 * DataResultView — shared, schema-agnostic renderer for arbitrary JSON result
 * data. Promoted out of the System MCP admin screen for site-wide reuse: any
 * surface that shows "what did this node / block / query actually return" can
 * drop it in.
 *
 * Three views, switchable client-side with no refetch:
 *   - structured : array-of-objects → table (nested cells collapse to a chip,
 *                  click a row to expand its full record); single object →
 *                  scalar mini-card grid.
 *   - tree       : collapsible JSON tree (expand-all / collapse-all).
 *   - raw        : pretty-printed JSON.
 * Plus copy-to-clipboard and an optional fullscreen toggle (Esc to exit).
 *
 * It does NOT render charts or schema-driven (output_schema) reports — those
 * stay with ChartRenderer / SkillOutputRenderer respectively. This is the
 * raw-data inspector.
 */

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { T } from "./uiTokens";

interface Props {
  result: unknown;              // parsed response/value (not a string)
  loading?: boolean;
  error?: string | null;
  latencyMs?: number | null;    // optional duration shown on the meta line
  /** Left-most meta slot, e.g. a "200 OK" badge. Omit for a plain count line. */
  statusSlot?: ReactNode;
  loadingText?: string;
  emptyText?: string;
  defaultView?: View;
  maxRows?: number;
  /** Show the fullscreen toggle. Disable when embedded in a modal/canvas. */
  enableFullscreen?: boolean;
  /**
   * Optional per-row highlight predicate for the structured table. The rule
   * lives at the call site (e.g. an alarm view marks OOC / triggered rows) so
   * the generic component stays free of domain-specific logic.
   */
  rowHighlight?: (row: Record<string, unknown>) => boolean;
}

type View = "structured" | "tree" | "raw";

const ARRAY_KEYS = ["events", "data", "items", "results", "rows", "records", "list"];
const DEFAULT_MAX_ROWS = 200;

/** Find the primary array-of-objects to tabulate. */
function findTable(result: unknown): { rows: Record<string, unknown>[]; sourceKey: string | null } {
  if (Array.isArray(result) && result.every(r => r && typeof r === "object" && !Array.isArray(r))) {
    return { rows: result as Record<string, unknown>[], sourceKey: null };
  }
  if (result && typeof result === "object" && !Array.isArray(result)) {
    const obj = result as Record<string, unknown>;
    for (const k of ARRAY_KEYS) {
      const v = obj[k];
      if (Array.isArray(v) && v.length > 0 && v.every(r => r && typeof r === "object" && !Array.isArray(r))) {
        return { rows: v as Record<string, unknown>[], sourceKey: k };
      }
    }
    for (const [k, v] of Object.entries(obj)) {
      if (Array.isArray(v) && v.length > 0 && v.every(r => r && typeof r === "object" && !Array.isArray(r))) {
        return { rows: v as Record<string, unknown>[], sourceKey: k };
      }
    }
  }
  return { rows: [], sourceKey: null };
}

/** Count the rows the viewer reports (events/data length, else total/count, else 1). */
function countOf(result: unknown): number {
  const { rows } = findTable(result);
  if (rows.length) return rows.length;
  if (Array.isArray(result)) return result.length;
  if (result && typeof result === "object") {
    const n = (result as Record<string, unknown>).total ?? (result as Record<string, unknown>).count;
    if (typeof n === "number") return n;
  }
  return 1;
}

function statusTone(v: unknown): "ooc" | "pass" | undefined {
  const s = String(v).toUpperCase();
  if (s === "OOC" || s === "FAIL" || s === "FAULT" || s === "NG" || s === "ALARM") return "ooc";
  if (s === "PASS" || s === "OK" || s === "NORMAL" || s === "GOOD") return "pass";
  return undefined;
}

function fmtScalar(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : Number(v.toPrecision(6)).toString();
  return String(v);
}

export default function DataResultView({
  result, loading, error, latencyMs, statusSlot,
  loadingText = "載入中…", emptyText = "尚無資料",
  defaultView = "structured", maxRows = DEFAULT_MAX_ROWS, enableFullscreen = true, rowHighlight,
}: Props) {
  const [view, setView] = useState<View>(defaultView);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [treeOpen, setTreeOpen] = useState<Record<string, boolean>>({});
  const [flash, setFlash] = useState<string | null>(null);

  const { rows, sourceKey } = useMemo(() => findTable(result), [result]);
  const columns = useMemo(() => {
    const set = new Set<string>();
    rows.slice(0, maxRows).forEach(r => Object.keys(r).forEach(k => set.add(k)));
    return Array.from(set);
  }, [rows, maxRows]);

  // A fresh result invalidates per-result UI state.
  useEffect(() => { setExpandedRow(null); setTreeOpen({}); }, [result]);
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  if (loading) return <Shell><Center>{loadingText}</Center></Shell>;
  if (error) {
    return (
      <Shell>
        <div style={{ background: "#fff5f5", border: `1px solid ${T.dangerBd}`, borderRadius: 8, padding: "14px 16px", color: T.oocT }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>[no] 失敗</div>
          <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", fontFamily: T.mono }}>{error}</pre>
        </div>
      </Shell>
    );
  }
  if (result === null || result === undefined) {
    return <Shell><Center>{emptyText}</Center></Shell>;
  }

  const isTable = rows.length > 0;
  const copy = () => {
    try { navigator.clipboard?.writeText(JSON.stringify(result, null, 2)); setFlash("已複製"); setTimeout(() => setFlash(null), 1200); }
    catch { /* clipboard unavailable */ }
  };
  const setAllTree = (open: boolean) => setTreeOpen(open ? collectPaths(result) : {});

  const meta = (
    <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", fontFamily: T.mono, fontSize: 12, color: T.muted }}>
      {statusSlot}
      <span>{countOf(result)} 筆{sourceKey ? ` · ${sourceKey}` : ""}{rows.length > maxRows ? `（顯示前 ${maxRows}）` : ""}</span>
      {latencyMs != null && <span style={{ color: T.faint }}>{latencyMs} ms</span>}
      {flash && <b style={{ color: T.accent }}>{flash}</b>}
    </div>
  );

  const toolbar = (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
      <div style={{ display: "inline-flex", background: "#f1f5f9", borderRadius: 9, padding: 3, gap: 2 }}>
        {(["structured", "tree", "raw"] as View[]).map(v => (
          <button key={v} onClick={() => setView(v)} style={{
            fontFamily: T.mono, fontSize: 12, fontWeight: 600, border: "none", borderRadius: 7,
            padding: "5px 12px", cursor: "pointer",
            background: view === v ? T.accent : "transparent", color: view === v ? "#fff" : T.muted,
          }}>{v}</button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        {view === "tree" && <>
          <IconBtn onClick={() => setAllTree(true)}>⊞ 展開全部</IconBtn>
          <IconBtn onClick={() => setAllTree(false)}>⊟ 收合</IconBtn>
        </>}
        <IconBtn onClick={copy}>⧉ copy</IconBtn>
        {enableFullscreen && <IconBtn onClick={() => setFullscreen(f => !f)}>{fullscreen ? "⤡ exit" : "⤢ fullscreen"}</IconBtn>}
      </div>
    </div>
  );

  const body = (
    <div style={{
      border: `1px solid ${T.bd}`, borderRadius: 12, overflow: "hidden",
      display: "flex", flexDirection: "column", flex: 1, minHeight: 0,
    }}>
      <div style={{ padding: 16, overflow: "auto", flex: 1, minHeight: 0, fontFamily: T.mono, fontSize: 12.5, lineHeight: 1.55 }}>
        {view === "raw" && <pre style={{ margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.65 }}>{JSON.stringify(result, null, 2)}</pre>}
        {view === "tree" && <TreeNode value={result} k="root" path="root" depth={0} open={treeOpen} setOpen={setTreeOpen} />}
        {view === "structured" && (isTable
          ? <DataTable rows={rows} columns={columns} maxRows={maxRows} expanded={expandedRow} setExpanded={setExpandedRow} rowHighlight={rowHighlight} />
          : <CardGrid value={result} />)}
      </div>
    </div>
  );

  if (fullscreen) {
    return (
      <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "#fff", display: "flex", flexDirection: "column", padding: 18, gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 700 }}>result</span>
          {meta}
        </div>
        {toolbar}
        {body}
      </div>
    );
  }

  return (
    <Shell>
      <div style={{ marginBottom: 10 }}>{meta}</div>
      <div style={{ marginBottom: 10 }}>{toolbar}</div>
      {body}
    </Shell>
  );
}

// ── structured: table ───────────────────────────────────────────────────────

function DataTable({ rows, columns, maxRows, expanded, setExpanded, rowHighlight }: {
  rows: Record<string, unknown>[]; columns: string[]; maxRows: number;
  expanded: number | null; setExpanded: (i: number | null) => void;
  rowHighlight?: (row: Record<string, unknown>) => boolean;
}) {
  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontFamily: T.mono, fontSize: 12.5, whiteSpace: "nowrap" }}>
      <thead>
        <tr>
          <th style={th}>#</th>
          {columns.map(c => <th key={c} style={th}>{c}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, maxRows).map((r, i) => {
          const open = expanded === i;
          const hl = rowHighlight?.(r) ?? false;
          return (
            <Fragment key={i}>
              <tr onClick={() => setExpanded(open ? null : i)}
                  style={{ cursor: "pointer", background: open ? T.accentBg : hl ? T.oocBg : i % 2 ? T.panel : undefined }}>
                <td style={{ ...td, color: open ? T.accent : hl ? T.oocT : T.faint2 }}>{open ? "▾" : i + 1}</td>
                {columns.map(c => <td key={c} style={{ ...td, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}
                  title={typeof r[c] === "object" && r[c] ? JSON.stringify(r[c]) : String(r[c] ?? "")}>{cell(r[c])}</td>)}
              </tr>
              {open && (
                <tr>
                  <td colSpan={columns.length + 1} style={{ padding: "10px 14px", background: "#fafbfe", whiteSpace: "normal", borderBottom: `2px solid ${T.bd}` }}>
                    <div style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: "8px 12px" }}>
                      {Object.entries(r).map(([k, v]) => (
                        <Fragment key={k}>
                          <span style={{ color: T.jKey, fontWeight: 600 }}>{k}</span>
                          <span>{typeof v === "object" && v
                            ? <pre style={{ margin: 0, fontSize: 11.5, whiteSpace: "pre-wrap" }}>{JSON.stringify(v, null, 2)}</pre>
                            : scalar(v)}</span>
                        </Fragment>
                      ))}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

/** Compact table cell: nested object/array → chip; scalar → coloured text. */
function cell(v: unknown) {
  if (Array.isArray(v)) return <Chip>[{v.length}]</Chip>;
  if (v && typeof v === "object") return <Chip>{`{${Object.keys(v).length}}`}</Chip>;
  return scalar(v);
}

function scalar(v: unknown) {
  const tone = statusTone(v);
  if (tone === "ooc") return <span style={{ color: T.oocT, background: T.oocBg, fontWeight: 700, borderRadius: 5, padding: "1px 6px" }}>{String(v)}</span>;
  if (tone === "pass") return <span style={{ color: T.okT, fontWeight: 700 }}>{String(v)}</span>;
  if (v === null || v === undefined) return <span style={{ color: T.jNull }}>—</span>;
  if (typeof v === "number") return <span style={{ color: T.jNum }}>{fmtScalar(v)}</span>;
  if (typeof v === "boolean") return <span style={{ color: T.jBool }}>{String(v)}</span>;
  return <span style={{ color: T.jStr }}>{String(v)}</span>;
}

function Chip({ children }: { children: ReactNode }) {
  return <span style={{ fontSize: 11, fontWeight: 600, color: T.accent, background: T.accentBg, borderRadius: 20, padding: "1px 8px" }}>{children}</span>;
}

// ── structured: single-object card grid ─────────────────────────────────────

function CardGrid({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <pre style={{ margin: 0 }}>{JSON.stringify(value, null, 2)}</pre>;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 8 }}>
      {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
        <div key={k} style={{ border: `1px solid ${T.bdIn}`, borderRadius: 10, padding: "10px 12px", background: "#fff", minWidth: 0 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", color: T.muted }}>{k}</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis" }}>{cell(v)}</div>
        </div>
      ))}
    </div>
  );
}

// ── tree ────────────────────────────────────────────────────────────────────

function collectPaths(value: unknown, path = "root", acc: Record<string, boolean> = {}): Record<string, boolean> {
  if (value && typeof value === "object") {
    acc[path] = true;
    const entries = Array.isArray(value) ? value.map((v, i) => [i, v] as const) : Object.entries(value);
    entries.forEach(([k, v]) => collectPaths(v, `${path}.${k}`, acc));
  }
  return acc;
}

function TreeNode({ value, k, path, depth, open, setOpen }: {
  value: unknown; k: string | number; path: string; depth: number;
  open: Record<string, boolean>; setOpen: (f: (o: Record<string, boolean>) => Record<string, boolean>) => void;
}) {
  const isObj = value && typeof value === "object";
  if (!isObj) {
    return <div><span style={{ display: "inline-block", width: 14 }} /><span style={{ color: T.jKey }}>{k}</span>: {scalar(value)}</div>;
  }
  const isArr = Array.isArray(value);
  const entries = isArr ? (value as unknown[]).map((v, i) => [i, v] as const) : Object.entries(value as Record<string, unknown>);
  const isOpen = depth === 0 ? open[path] ?? true : open[path] ?? false;
  return (
    <div>
      <div onClick={() => setOpen(o => ({ ...o, [path]: !isOpen }))} style={{ cursor: "pointer" }}>
        <span style={{ display: "inline-block", width: 14, color: T.faint }}>{isOpen ? "▾" : "▶"}</span>
        <span style={{ color: T.jKey }}>{k}</span>{" "}
        {isOpen ? (isArr ? "[" : "{") : <span style={{ fontStyle: "italic", color: T.muted }}>{isArr ? `Array(${entries.length})` : `Object(${entries.length})`}</span>}
      </div>
      {isOpen && (
        <>
          <div style={{ paddingLeft: 13, borderLeft: `1px solid ${T.hair}`, marginLeft: 6 }}>
            {entries.map(([ck, cv]) => (
              <TreeNode key={ck} value={cv} k={ck} path={`${path}.${ck}`} depth={depth + 1} open={open} setOpen={setOpen} />
            ))}
          </div>
          <div>{isArr ? "]" : "}"}</div>
        </>
      )}
    </div>
  );
}

// ── shells ──────────────────────────────────────────────────────────────────

function Shell({ children }: { children: ReactNode }) {
  return <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>{children}</div>;
}
function Center({ children }: { children: ReactNode }) {
  return <div style={{ color: T.faint, fontSize: 13, padding: 40, textAlign: "center" }}>{children}</div>;
}
function IconBtn({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button onClick={onClick} style={{
    fontFamily: T.mono, fontSize: 11.5, fontWeight: 600, border: `1px solid ${T.bd}`, background: "#fff",
    borderRadius: 7, padding: "5px 10px", color: T.muted, cursor: "pointer",
  }}>{children}</button>;
}

const th: React.CSSProperties = {
  position: "sticky", top: 0, background: T.panel, color: T.muted, fontSize: 11, fontWeight: 700,
  textTransform: "uppercase", textAlign: "left", padding: "8px 12px", borderBottom: `1px solid ${T.bd}`, whiteSpace: "nowrap",
};
const td: React.CSSProperties = { padding: "7px 12px", borderBottom: `1px solid ${T.hair}`, verticalAlign: "top" };

/** Convenience meta slot: a green "200 OK"-style status badge. */
export function OkStatus({ label = "200 OK" }: { label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: T.dot, display: "inline-block" }} />{label}
    </span>
  );
}
