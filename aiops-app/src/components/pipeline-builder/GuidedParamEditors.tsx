"use client";

/**
 * GuidedParamEditors (2026-07-13, user 回報「積木不該讓人寫 code/編 JSON」)
 * — 全平台掃描出 20 個 JSON-hostile 參數，這裡補齊四類編輯器：
 *
 *   ConditionsEditor   filter.conditions        逐列 欄位/運算子/值 + and|or
 *   AggregationsEditor groupby.aggregations     逐列 欄位/函式/輸出名
 *   RulesEditor        chart rules              逐列 標籤/數值/樣式（管制線）
 *   KeyValueEditor     mcp args / chart style   key-value 表格（值自動型別）
 *   JsonFallbackEditor 資料直灌 array/object    誠實 JSON textarea + 提示
 *
 * 共同原則：本地列狀態允許空列、對外只吐有效值；上游欄名 datalist；
 * 值輸入自動型別（"3.5"→number、"true"→bool）。
 */
import React from "react";

import type { ColumnsByPort } from "@/context/pipeline-builder/useUpstreamColumns";

export interface EditorProps {
  name: string;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  borderColor: string;
  commonStyle: React.CSSProperties;
  upstreamColumns?: ColumnsByPort;
}

function coerceLit(s: string): unknown {
  const t = s.trim();
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return t;
}
const litToStr = (v: unknown): string => (v == null ? "" : String(v));

function useCols(upstreamColumns?: ColumnsByPort): string[] {
  return upstreamColumns ? Array.from(new Set(Object.values(upstreamColumns).flat())) : [];
}

const addBtnStyle = (borderColor: string): React.CSSProperties => ({
  alignSelf: "flex-start", border: `1px dashed ${borderColor}`, background: "none",
  color: "#64748B", fontSize: 11, padding: "3px 10px", borderRadius: 6, cursor: "pointer",
});
const xBtnStyle: React.CSSProperties = {
  border: "none", background: "none", cursor: "pointer", color: "#94A3B8",
  fontSize: 12, padding: "0 2px", flexShrink: 0,
};
const rowStyle: React.CSSProperties = { display: "flex", gap: 4, alignItems: "center" };

// ── filter.conditions ────────────────────────────────────────────────────
const FILTER_OPS = ["==", "!=", ">", "<", ">=", "<=", "contains", "in", "not_in"];

type Cond = { column: string; operator: string; value: string };

export function ConditionsEditor(p: EditorProps) {
  const cols = useCols(p.upstreamColumns);
  const listId = `cond-cols-${p.name}`;
  const [rows, setRows] = React.useState<Cond[]>(() => {
    const v = Array.isArray(p.value) ? (p.value as Array<Record<string, unknown>>) : [];
    const r = v.map((c) => ({
      column: String(c?.column ?? ""), operator: String(c?.operator ?? "=="),
      value: Array.isArray(c?.value) ? JSON.stringify(c.value) : litToStr(c?.value),
    }));
    return r.length ? r : [{ column: "", operator: "==", value: "" }];
  });
  const sync = (next: Cond[]) => {
    setRows(next.length ? next : [{ column: "", operator: "==", value: "" }]);
    const out = next.filter((r) => r.column.trim()).map((r) => ({
      column: r.column.trim(), operator: r.operator,
      value: (r.operator === "in" || r.operator === "not_in")
        ? (() => { try { return JSON.parse(r.value); } catch { return r.value.split(",").map((s) => coerceLit(s)); } })()
        : coerceLit(r.value),
    }));
    p.onChange(out.length ? out : undefined);
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map((r, i) => (
        <div key={i} style={rowStyle}>
          <input type="text" value={r.column} disabled={p.disabled} placeholder="欄位"
            list={cols.length ? listId : undefined} autoComplete="off"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1.2 }} />
          <select value={r.operator} disabled={p.disabled}
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, operator: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, width: 88, flexShrink: 0 }}>
            {FILTER_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <input type="text" value={r.value} disabled={p.disabled}
            placeholder={(r.operator === "in" || r.operator === "not_in") ? "值1, 值2, …" : "值"}
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1 }} />
          <button type="button" style={xBtnStyle} disabled={p.disabled || rows.length <= 1}
            onClick={() => sync(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" style={addBtnStyle(p.borderColor)} disabled={p.disabled}
        onClick={() => setRows((prev) => [...prev, { column: "", operator: "==", value: "" }])}>
        ＋ 加條件
      </button>
      {cols.length > 0 && <datalist id={listId}>{cols.map((c) => <option key={c} value={c} />)}</datalist>}
    </div>
  );
}

// ── groupby.aggregations ─────────────────────────────────────────────────
const AGG_FUNCS = ["mean", "sum", "count", "min", "max", "median", "std"];

type AggRow = { column: string; func: string; as: string };

export function AggregationsEditor(p: EditorProps) {
  const cols = useCols(p.upstreamColumns);
  const listId = `agg-cols-${p.name}`;
  const [rows, setRows] = React.useState<AggRow[]>(() => {
    const v = Array.isArray(p.value) ? (p.value as Array<Record<string, unknown>>) : [];
    const r = v.map((a) => ({
      column: String(a?.column ?? ""), func: String(a?.func ?? "mean"), as: String(a?.as ?? ""),
    }));
    return r.length ? r : [{ column: "", func: "mean", as: "" }];
  });
  const sync = (next: AggRow[]) => {
    setRows(next.length ? next : [{ column: "", func: "mean", as: "" }]);
    const out = next.filter((r) => r.column.trim()).map((r) => ({
      column: r.column.trim(), func: r.func,
      ...(r.as.trim() ? { as: r.as.trim() } : {}),
    }));
    p.onChange(out.length ? out : undefined);
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map((r, i) => (
        <div key={i} style={rowStyle}>
          <input type="text" value={r.column} disabled={p.disabled} placeholder="聚合欄位"
            list={cols.length ? listId : undefined} autoComplete="off"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1.2 }} />
          <select value={r.func} disabled={p.disabled}
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, func: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, width: 86, flexShrink: 0 }}>
            {AGG_FUNCS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          <input type="text" value={r.as} disabled={p.disabled} placeholder="輸出名（選填）"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, as: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1 }} />
          <button type="button" style={xBtnStyle} disabled={p.disabled || rows.length <= 1}
            onClick={() => sync(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" style={addBtnStyle(p.borderColor)} disabled={p.disabled}
        onClick={() => setRows((prev) => [...prev, { column: "", func: "mean", as: "" }])}>
        ＋ 加聚合
      </button>
      {cols.length > 0 && <datalist id={listId}>{cols.map((c) => <option key={c} value={c} />)}</datalist>}
    </div>
  );
}

// ── chart rules（管制線）────────────────────────────────────────────────
const RULE_STYLES = [
  { v: "limit", label: "管制限（紅虛線）" },
  { v: "center", label: "中心線（點虛線）" },
];

type RuleRow = { label: string; value: string; style: string };

export function RulesEditor(p: EditorProps) {
  const [rows, setRows] = React.useState<RuleRow[]>(() => {
    const v = Array.isArray(p.value) ? (p.value as Array<Record<string, unknown>>) : [];
    const r = v.map((x) => ({
      label: String(x?.label ?? ""), value: litToStr(x?.value), style: String(x?.style ?? "limit"),
    }));
    return r.length ? r : [{ label: "", value: "", style: "limit" }];
  });
  const sync = (next: RuleRow[]) => {
    setRows(next.length ? next : [{ label: "", value: "", style: "limit" }]);
    const out = next
      .filter((r) => r.label.trim() && r.value.trim() !== "" && Number.isFinite(Number(r.value)))
      .map((r) => ({ label: r.label.trim(), value: Number(r.value), style: r.style }));
    p.onChange(out.length ? out : undefined);
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map((r, i) => (
        <div key={i} style={rowStyle}>
          <input type="text" value={r.label} disabled={p.disabled} placeholder="標籤（如 UCL）"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1 }} />
          <input type="number" value={r.value} disabled={p.disabled} placeholder="數值"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, width: 92, flexShrink: 0 }} />
          <select value={r.style} disabled={p.disabled}
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, style: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, width: 128, flexShrink: 0 }}>
            {RULE_STYLES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
          </select>
          <button type="button" style={xBtnStyle} disabled={p.disabled || rows.length <= 1}
            onClick={() => sync(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" style={addBtnStyle(p.borderColor)} disabled={p.disabled}
        onClick={() => setRows((prev) => [...prev, { label: "", value: "", style: "limit" }])}>
        ＋ 加一條線
      </button>
      <span style={{ fontSize: 10, color: "#94A3B8" }}>
        固定值的水平參考線；管制限若在上游資料欄（每列不同值）改用 ucl_column/lcl_column 參數。
      </span>
    </div>
  );
}

// ── 通用 key-value（mcp args / chart style）─────────────────────────────
type KvRow = { k: string; v: string };

export function KeyValueEditor(p: EditorProps & { hint?: string }) {
  const [rows, setRows] = React.useState<KvRow[]>(() => {
    const v = p.value && typeof p.value === "object" && !Array.isArray(p.value)
      ? Object.entries(p.value as Record<string, unknown>) : [];
    const r = v.map(([k, val]) => ({
      k, v: typeof val === "object" ? JSON.stringify(val) : litToStr(val),
    }));
    return r.length ? r : [{ k: "", v: "" }];
  });
  const sync = (next: KvRow[]) => {
    setRows(next.length ? next : [{ k: "", v: "" }]);
    const out: Record<string, unknown> = {};
    for (const r of next) {
      if (!r.k.trim()) continue;
      const t = r.v.trim();
      if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
        try { out[r.k.trim()] = JSON.parse(t); continue; } catch { /* 當字串 */ }
      }
      out[r.k.trim()] = coerceLit(r.v);
    }
    p.onChange(Object.keys(out).length ? out : undefined);
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map((r, i) => (
        <div key={i} style={rowStyle}>
          <input type="text" value={r.k} disabled={p.disabled} placeholder="參數名"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1, fontFamily: "ui-monospace, Menlo, monospace" }} />
          <span style={{ fontSize: 11, color: "#94A3B8", flexShrink: 0 }}>=</span>
          <input type="text" value={r.v} disabled={p.disabled} placeholder="值（數字/文字/true）"
            onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))}
            style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1.4 }} />
          <button type="button" style={xBtnStyle} disabled={p.disabled || rows.length <= 1}
            onClick={() => sync(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" style={addBtnStyle(p.borderColor)} disabled={p.disabled}
        onClick={() => setRows((prev) => [...prev, { k: "", v: "" }])}>
        ＋ 加參數
      </button>
      {p.hint && <span style={{ fontSize: 10, color: "#94A3B8" }}>{p.hint}</span>}
    </div>
  );
}

// ── data_view.highlight_rules（S3 條件格式化）───────────────────────────
type HlRow = { column: string; operator: string; value: string; background: string; text_color: string };

const HL_PRESETS = [
  { label: "紅底", background: "#FDE8E9", text_color: "#B4232D" },
  { label: "琥珀底", background: "#FBEECF", text_color: "#8a5a06" },
  { label: "綠底", background: "#E5F5EC", text_color: "#047857" },
];

export function HighlightRulesEditor(p: EditorProps) {
  const cols = useCols(p.upstreamColumns);
  const listId = `hl-cols-${p.name}`;
  const [rows, setRows] = React.useState<HlRow[]>(() => {
    const v = Array.isArray(p.value) ? (p.value as Array<Record<string, unknown>>) : [];
    const r = v.map((x) => ({
      column: String(x?.column ?? ""), operator: String(x?.operator ?? "=="),
      value: litToStr(x?.value),
      background: String(x?.background ?? "#FDE8E9"),
      text_color: String(x?.text_color ?? "#B4232D"),
    }));
    return r.length ? r : [{ column: "", operator: "==", value: "", background: "#FDE8E9", text_color: "#B4232D" }];
  });
  const sync = (next: HlRow[]) => {
    setRows(next.length ? next : [{ column: "", operator: "==", value: "", background: "#FDE8E9", text_color: "#B4232D" }]);
    const out = next.filter((r) => r.column.trim()).map((r) => ({
      column: r.column.trim(), operator: r.operator, value: coerceLit(r.value),
      background: r.background, text_color: r.text_color,
    }));
    p.onChange(out.length ? out : undefined);
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", gap: 3,
                              border: "1px solid #EEF2F6", borderRadius: 7, padding: "5px 6px" }}>
          <div style={rowStyle}>
            <input type="text" value={r.column} disabled={p.disabled} placeholder="欄位"
              list={cols.length ? listId : undefined} autoComplete="off"
              onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}
              style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1.2 }} />
            <select value={r.operator} disabled={p.disabled}
              onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, operator: e.target.value } : x)))}
              style={{ ...p.commonStyle, borderColor: p.borderColor, width: 86, flexShrink: 0 }}>
              {FILTER_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <input type="text" value={r.value} disabled={p.disabled} placeholder="值"
              onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
              style={{ ...p.commonStyle, borderColor: p.borderColor, flex: 1 }} />
            <button type="button" style={xBtnStyle} disabled={p.disabled || rows.length <= 1}
              onClick={() => sync(rows.filter((_, j) => j !== i))}>✕</button>
          </div>
          <div style={{ ...rowStyle, paddingLeft: 2 }}>
            <span style={{ fontSize: 10.5, color: "#94A3B8", flexShrink: 0 }}>命中時</span>
            {HL_PRESETS.map((pr) => (
              <button key={pr.label} type="button" disabled={p.disabled}
                onClick={() => sync(rows.map((x, j) => (j === i ? { ...x, background: pr.background, text_color: pr.text_color } : x)))}
                style={{ fontSize: 10.5, padding: "2px 9px", borderRadius: 9, cursor: "pointer",
                         background: pr.background, color: pr.text_color,
                         border: r.background === pr.background ? `1.5px solid ${pr.text_color}` : "1px solid #E2E8F0",
                         fontWeight: r.background === pr.background ? 700 : 400 }}>{pr.label}</button>
            ))}
            <input type="color" value={r.background} disabled={p.disabled} title="自訂背景色"
              onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, background: e.target.value } : x)))}
              style={{ width: 26, height: 22, padding: 0, border: "1px solid #E2E8F0", borderRadius: 5, cursor: "pointer" }} />
            <input type="color" value={r.text_color} disabled={p.disabled} title="自訂字色"
              onChange={(e) => sync(rows.map((x, j) => (j === i ? { ...x, text_color: e.target.value } : x)))}
              style={{ width: 26, height: 22, padding: 0, border: "1px solid #E2E8F0", borderRadius: 5, cursor: "pointer" }} />
          </div>
        </div>
      ))}
      <button type="button" style={addBtnStyle(p.borderColor)} disabled={p.disabled}
        onClick={() => setRows((prev) => [...prev, { column: "", operator: "==", value: "", background: "#FDE8E9", text_color: "#B4232D" }])}>
        ＋ 加規則
      </button>
      {cols.length > 0 && <datalist id={listId}>{cols.map((c) => <option key={c} value={c} />)}</datalist>}
    </div>
  );
}

// ── 資料直灌 array / 其他複雜參數：誠實 JSON textarea ────────────────────
export function JsonFallbackEditor(p: EditorProps & { hint?: string }) {
  const [text, setText] = React.useState<string>(() =>
    p.value == null ? "" : JSON.stringify(p.value, null, 1));
  const [err, setErr] = React.useState("");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <textarea value={text} rows={4} disabled={p.disabled}
        placeholder="JSON（此參數通常由上游資料供給，一般不需手填）"
        onChange={(e) => {
          setText(e.target.value);
          const t = e.target.value.trim();
          if (!t) { setErr(""); p.onChange(undefined); return; }
          try { p.onChange(JSON.parse(t)); setErr(""); }
          catch { setErr("JSON 尚未合法 — 未寫入"); }
        }}
        style={{ ...p.commonStyle, borderColor: p.borderColor,
                 fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11, resize: "vertical" }} />
      {err && <span style={{ fontSize: 10.5, color: "#B45309" }}>{err}</span>}
      {p.hint && <span style={{ fontSize: 10, color: "#94A3B8" }}>{p.hint}</span>}
    </div>
  );
}
