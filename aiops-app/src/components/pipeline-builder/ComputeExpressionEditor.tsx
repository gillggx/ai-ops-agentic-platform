"use client";

/**
 * ComputeExpressionEditor (2026-07-13, user 回報) — block_compute 的 expression
 * 給人用的表單版。之前是裸 JSON textarea（expression tree），等於要人寫 code。
 *
 * 四種常用模式用表單填，各自組出正確的 expression tree；認不得的既有樹
 * 落到「進階 JSON」模式（原樣可編）。跟 SortColumnsEditor / FieldsEditor
 * 同一套 guided-editor 模式。
 */
import React from "react";

import type { ColumnsByPort } from "@/context/pipeline-builder/useUpstreamColumns";

type Mode = "if" | "concat" | "arith" | "cast" | "json";

const CMP_OPS = [
  { v: "eq", label: "＝" }, { v: "ne", label: "≠" },
  { v: "gt", label: "＞" }, { v: "gte", label: "≥" },
  { v: "lt", label: "＜" }, { v: "lte", label: "≤" },
];
const ARITH_OPS = [
  { v: "add", label: "＋" }, { v: "sub", label: "－" },
  { v: "mul", label: "×" }, { v: "div", label: "÷" },
  { v: "abs", label: "|絕對值|" },  // 單元 — 只用左運算元
];
const CAST_OPS = [
  { v: "as_int", label: "整數 int" }, { v: "as_float", label: "小數 float" },
  { v: "as_str", label: "字串 str" }, { v: "as_bool", label: "布林 bool" },
];

/** 值輸入的小工具：字串 "3.5" → 3.5、"true" → true，其餘保留字串。 */
function coerceLit(s: string): unknown {
  const t = s.trim();
  if (t === "") return "";
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return t;
}
function litToStr(v: unknown): string { return v == null ? "" : String(v); }

/** 欄位或常數的一格：chip 切換「欄位 / 值」。 */
interface Operand { kind: "column" | "value"; text: string }
function operandToNode(o: Operand): unknown {
  return o.kind === "column" ? { column: o.text.trim() } : coerceLit(o.text);
}
function nodeToOperand(n: unknown): Operand | null {
  if (n && typeof n === "object" && !Array.isArray(n)) {
    const col = (n as { column?: unknown }).column;
    if (typeof col === "string") return { kind: "column", text: col };
    return null; // 巢狀 op — 表單模式不支援
  }
  return { kind: "value", text: litToStr(n) };
}

interface IfState { col: string; cmp: string; cmpVal: string; thenV: Operand; elseV: Operand }
interface ArithState { a: Operand; op: string; b: Operand }
interface CastState { op: string; col: string }

interface Parsed {
  mode: Mode;
  ifS?: IfState; concatS?: Operand[]; arithS?: ArithState; castS?: CastState;
}

/** 既有 expression tree → 表單狀態；認不得回 json 模式。 */
function parseExpr(v: unknown): Parsed {
  if (!v || typeof v !== "object" || Array.isArray(v)) {
    return { mode: "if", ifS: emptyIf() };  // 空值 → 預設條件模式
  }
  const node = v as { op?: string; operands?: unknown[] };
  const ops = node.operands ?? [];
  if (node.op === "if" && ops.length === 3) {
    const cond = ops[0] as { op?: string; operands?: unknown[] };
    const cOps = cond?.operands ?? [];
    const colN = cOps[0] as { column?: unknown } | undefined;
    const thenO = nodeToOperand(ops[1]);
    const elseO = nodeToOperand(ops[2]);
    if (cond?.op && CMP_OPS.some((c) => c.v === cond.op) && typeof colN?.column === "string"
        && cOps.length === 2 && !isNode(cOps[1]) && thenO && elseO) {
      return { mode: "if", ifS: {
        col: colN.column, cmp: cond.op, cmpVal: litToStr(cOps[1]),
        thenV: thenO, elseV: elseO } };
    }
    return { mode: "json" };
  }
  if (node.op === "concat") {
    const parts = ops.map(nodeToOperand);
    if (parts.every(Boolean)) return { mode: "concat", concatS: parts as Operand[] };
    return { mode: "json" };
  }
  if (node.op === "abs" && ops.length === 1) {
    const a = nodeToOperand(ops[0]);
    if (a) return { mode: "arith", arithS: { a, op: "abs", b: { kind: "value", text: "" } } };
    return { mode: "json" };
  }
  if (node.op && ARITH_OPS.some((a) => a.v === node.op) && ops.length === 2) {
    const a = nodeToOperand(ops[0]); const b = nodeToOperand(ops[1]);
    if (a && b) return { mode: "arith", arithS: { a, op: node.op, b } };
    return { mode: "json" };
  }
  if (node.op && CAST_OPS.some((c) => c.v === node.op) && ops.length === 1) {
    const colN = ops[0] as { column?: unknown };
    if (typeof colN?.column === "string") return { mode: "cast", castS: { op: node.op, col: colN.column } };
    return { mode: "json" };
  }
  return { mode: "json" };
}
function isNode(x: unknown): boolean {
  return !!x && typeof x === "object" && !Array.isArray(x) &&
    ((x as { op?: unknown }).op != null || (x as { column?: unknown }).column != null);
}
function emptyIf(): IfState {
  return { col: "", cmp: "eq", cmpVal: "",
           thenV: { kind: "value", text: "1" }, elseV: { kind: "value", text: "0" } };
}

export function ComputeExpressionEditor({
  name, value, onChange, disabled, borderColor, commonStyle, upstreamColumns,
}: {
  name: string;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  borderColor: string;
  commonStyle: React.CSSProperties;
  upstreamColumns?: ColumnsByPort;
}) {
  const init = React.useMemo(() => parseExpr(value), []);  // eslint-disable-line react-hooks/exhaustive-deps
  const [mode, setMode] = React.useState<Mode>(init.mode);
  const [ifS, setIfS] = React.useState<IfState>(init.ifS ?? emptyIf());
  const [concatS, setConcatS] = React.useState<Operand[]>(
    init.concatS ?? [{ kind: "column", text: "" }, { kind: "value", text: "-" }]);
  const [arithS, setArithS] = React.useState<ArithState>(
    init.arithS ?? { a: { kind: "column", text: "" }, op: "add", b: { kind: "value", text: "" } });
  const [castS, setCastS] = React.useState<CastState>(init.castS ?? { op: "as_float", col: "" });
  const [jsonS, setJsonS] = React.useState<string>(() =>
    value && typeof value === "object" ? JSON.stringify(value, null, 1) : "");
  const [jsonErr, setJsonErr] = React.useState("");

  const cols = upstreamColumns
    ? Array.from(new Set(Object.values(upstreamColumns).flat()))
    : [];
  const listId = `compute-cols-${name}`;

  // 每次表單變動即組樹上拋（部分欄位空 = 上拋 undefined，等填完）
  const emit = (m: Mode, st: { ifS?: IfState; concatS?: Operand[]; arithS?: ArithState; castS?: CastState }) => {
    if (m === "if") {
      const s = st.ifS!;
      if (!s.col.trim()) return;
      onChange({ op: "if", operands: [
        { op: s.cmp, operands: [{ column: s.col.trim() }, coerceLit(s.cmpVal)] },
        operandToNode(s.thenV), operandToNode(s.elseV)] });
    } else if (m === "concat") {
      const parts = (st.concatS ?? []).filter((p) => p.text !== "");
      if (parts.length === 0) return;
      onChange({ op: "concat", operands: parts.map(operandToNode) });
    } else if (m === "arith") {
      const s = st.arithS!;
      if (!s.a.text.trim()) return;
      if (s.op === "abs") {
        onChange({ op: "abs", operands: [operandToNode(s.a)] });
        return;
      }
      if (!s.b.text.trim()) return;
      onChange({ op: s.op, operands: [operandToNode(s.a), operandToNode(s.b)] });
    } else if (m === "cast") {
      const s = st.castS!;
      if (!s.col.trim()) return;
      onChange({ op: s.op, operands: [{ column: s.col.trim() }] });
    }
  };

  const OperandInput = ({ v, onV, placeholder }: {
    v: Operand; onV: (o: Operand) => void; placeholder?: string;
  }) => (
    <span style={{ display: "inline-flex", gap: 3, alignItems: "center", flex: 1, minWidth: 0 }}>
      <button type="button" disabled={disabled}
        title={v.kind === "column" ? "目前：欄位值 — 點切成固定值" : "目前：固定值 — 點切成欄位值"}
        onClick={() => onV({ ...v, kind: v.kind === "column" ? "value" : "column" })}
        style={{ fontSize: 9.5, fontWeight: 700, padding: "2px 6px", borderRadius: 5,
                 border: `1px solid ${borderColor}`, cursor: "pointer", flexShrink: 0,
                 background: v.kind === "column" ? "var(--pl, #E4EEE7)" : "#fff",
                 color: v.kind === "column" ? "var(--pd, #14402F)" : "#64748B" }}>
        {v.kind === "column" ? "欄位" : "值"}
      </button>
      <input type="text" value={v.text} disabled={disabled}
        list={v.kind === "column" && cols.length ? listId : undefined}
        placeholder={placeholder ?? (v.kind === "column" ? "欄位名" : "固定值")}
        onChange={(e) => onV({ ...v, text: e.target.value })}
        style={{ ...commonStyle, borderColor, flex: 1, minWidth: 50 }} autoComplete="off" />
    </span>
  );

  const modeBtn = (m: Mode, label: string) => (
    <button key={m} type="button" disabled={disabled}
      onClick={() => { setMode(m); if (m !== "json") emit(m, { ifS, concatS, arithS, castS }); }}
      style={{ fontSize: 10.5, padding: "3px 9px", borderRadius: 10, cursor: "pointer",
               border: mode === m ? "1px solid var(--p, #1E5A44)" : `1px solid ${borderColor}`,
               background: mode === m ? "var(--pl, #E4EEE7)" : "#fff",
               color: mode === m ? "var(--pd, #14402F)" : "#64748B",
               fontWeight: mode === m ? 700 : 400 }}>{label}</button>
  );

  const rowStyle: React.CSSProperties = { display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {modeBtn("if", "條件標記")}
        {modeBtn("concat", "串接文字")}
        {modeBtn("arith", "算術")}
        {modeBtn("cast", "轉型")}
        {modeBtn("json", "進階 JSON")}
      </div>

      {mode === "if" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={rowStyle}>
            <span style={{ fontSize: 11, color: "#64748B", flexShrink: 0 }}>若</span>
            <input type="text" value={ifS.col} disabled={disabled}
              list={cols.length ? listId : undefined} placeholder="欄位（如 spc_status）"
              onChange={(e) => { const s = { ...ifS, col: e.target.value }; setIfS(s); emit("if", { ifS: s }); }}
              style={{ ...commonStyle, borderColor, flex: 1 }} autoComplete="off" />
            <select value={ifS.cmp} disabled={disabled}
              onChange={(e) => { const s = { ...ifS, cmp: e.target.value }; setIfS(s); emit("if", { ifS: s }); }}
              style={{ ...commonStyle, borderColor, width: 56, flexShrink: 0 }}>
              {CMP_OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
            <input type="text" value={ifS.cmpVal} disabled={disabled} placeholder="比較值（如 OOC）"
              onChange={(e) => { const s = { ...ifS, cmpVal: e.target.value }; setIfS(s); emit("if", { ifS: s }); }}
              style={{ ...commonStyle, borderColor, flex: 1 }} />
          </div>
          <div style={rowStyle}>
            <span style={{ fontSize: 11, color: "#64748B", flexShrink: 0 }}>成立 →</span>
            <OperandInput v={ifS.thenV} onV={(o) => { const s = { ...ifS, thenV: o }; setIfS(s); emit("if", { ifS: s }); }} />
            <span style={{ fontSize: 11, color: "#64748B", flexShrink: 0 }}>否則 →</span>
            <OperandInput v={ifS.elseV} onV={(o) => { const s = { ...ifS, elseV: o }; setIfS(s); emit("if", { ifS: s }); }} />
          </div>
        </div>
      )}

      {mode === "concat" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {concatS.map((p, i) => (
            <div key={i} style={rowStyle}>
              <span style={{ fontSize: 10, color: "#94A3B8", width: 14, textAlign: "right", flexShrink: 0 }}>{i + 1}.</span>
              <OperandInput v={p} onV={(o) => {
                const s = concatS.map((x, j) => (j === i ? o : x)); setConcatS(s); emit("concat", { concatS: s });
              }} placeholder={p.kind === "value" ? "文字（如 -）" : "欄位名"} />
              <button type="button" disabled={disabled || concatS.length <= 1} title="移除"
                onClick={() => { const s = concatS.filter((_, j) => j !== i); setConcatS(s); emit("concat", { concatS: s }); }}
                style={{ border: "none", background: "none", cursor: "pointer", color: "#94A3B8", fontSize: 12, flexShrink: 0 }}>✕</button>
            </div>
          ))}
          <button type="button" disabled={disabled}
            onClick={() => setConcatS((prev) => [...prev, { kind: "value", text: "" }])}
            style={{ alignSelf: "flex-start", border: `1px dashed ${borderColor}`, background: "none",
                     color: "#64748B", fontSize: 11, padding: "3px 10px", borderRadius: 6, cursor: "pointer" }}>
            ＋ 加一段
          </button>
        </div>
      )}

      {mode === "arith" && (
        <div style={rowStyle}>
          <OperandInput v={arithS.a} onV={(o) => { const s = { ...arithS, a: o }; setArithS(s); emit("arith", { arithS: s }); }} />
          <select value={arithS.op} disabled={disabled}
            onChange={(e) => { const s = { ...arithS, op: e.target.value }; setArithS(s); emit("arith", { arithS: s }); }}
            style={{ ...commonStyle, borderColor, width: 52, flexShrink: 0 }}>
            {ARITH_OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
          {arithS.op !== "abs" && (
            <OperandInput v={arithS.b} onV={(o) => { const s = { ...arithS, b: o }; setArithS(s); emit("arith", { arithS: s }); }} />
          )}
        </div>
      )}

      {mode === "cast" && (
        <div style={rowStyle}>
          <span style={{ fontSize: 11, color: "#64748B", flexShrink: 0 }}>把</span>
          <input type="text" value={castS.col} disabled={disabled}
            list={cols.length ? listId : undefined} placeholder="欄位名"
            onChange={(e) => { const s = { ...castS, col: e.target.value }; setCastS(s); emit("cast", { castS: s }); }}
            style={{ ...commonStyle, borderColor, flex: 1 }} autoComplete="off" />
          <span style={{ fontSize: 11, color: "#64748B", flexShrink: 0 }}>轉成</span>
          <select value={castS.op} disabled={disabled}
            onChange={(e) => { const s = { ...castS, op: e.target.value }; setCastS(s); emit("cast", { castS: s }); }}
            style={{ ...commonStyle, borderColor, width: 110, flexShrink: 0 }}>
            {CAST_OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
        </div>
      )}

      {mode === "json" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <textarea value={jsonS} rows={5} disabled={disabled}
            placeholder='{"op":"and","operands":[...]}（複合邏輯用這裡）'
            onChange={(e) => {
              setJsonS(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                setJsonErr(""); onChange(parsed);
              } catch { setJsonErr("JSON 尚未合法 — 未寫入"); }
            }}
            style={{ ...commonStyle, borderColor, fontFamily: "ui-monospace, Menlo, monospace",
                     fontSize: 11, resize: "vertical" }} />
          {jsonErr && <span style={{ fontSize: 10.5, color: "#B45309" }}>{jsonErr}</span>}
        </div>
      )}

      <span style={{ fontSize: 10, color: "#94A3B8" }}>
        產出欄位名在上面的「新欄位名稱」；這裡定義它的值怎麼算。複合條件（and/or 巢狀）用「進階 JSON」。
      </span>
      {cols.length > 0 && (
        <datalist id={listId}>{cols.map((c) => <option key={c} value={c} />)}</datalist>
      )}
    </div>
  );
}
