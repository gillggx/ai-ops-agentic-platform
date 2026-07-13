"use client";

/**
 * SortColumnsEditor (P4-4a, 2026-07-13) — 多鍵排序的逐鍵編輯器。
 * 觸發：param_schema 的 array items.oneOf 含 {column, order} 物件（block_sort
 * 的 columns）。逐列 = 欄位（datalist 上游欄名）+ asc/desc + 移除；「＋ 加
 * 排序鍵」新增。輸出保持 block 慣例：asc 用扁平字串、desc 用 {column, order}。
 * user 實測痛點：generic array widget 只能打逗號字串，方向根本沒法指定。
 */
import React from "react";

import type { ColumnsByPort } from "@/context/pipeline-builder/useUpstreamColumns";

type SortKey = { column: string; order: "asc" | "desc" };

function normalize(value: unknown): SortKey[] {
  if (typeof value === "string") {
    return value.split(",").map((s) => s.trim()).filter(Boolean)
      .map((c) => ({ column: c, order: "asc" as const }));
  }
  if (!Array.isArray(value)) return [];
  const out: SortKey[] = [];
  for (const entry of value as unknown[]) {
    if (typeof entry === "string") {
      for (const c of entry.split(",").map((s) => s.trim()).filter(Boolean)) {
        out.push({ column: c, order: "asc" });
      }
    } else if (entry && typeof entry === "object") {
      const o = entry as Record<string, unknown>;
      out.push({
        column: String(o.column ?? ""),
        order: o.order === "desc" ? "desc" : "asc",
      });
    }
  }
  return out;
}

export function SortColumnsEditor({
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
  // 本地列狀態（允許暫時空列）；對外 onChange 只吐有效鍵。
  const [display, setDisplay] = React.useState<SortKey[]>(() => {
    const rows = normalize(value);
    return rows.length ? rows : [{ column: "", order: "asc" }];
  });
  // 外部值變（還原舊 pipeline / agent 改參）→ 覆蓋本地列。
  const extKey = JSON.stringify(value ?? null);
  const lastExtKey = React.useRef(extKey);
  React.useEffect(() => {
    if (extKey === lastExtKey.current) return;
    lastExtKey.current = extKey;
    const rows = normalize(value);
    setDisplay(rows.length ? rows : [{ column: "", order: "asc" }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extKey]);

  const cols = upstreamColumns
    ? Array.from(new Set(Object.values(upstreamColumns).flat()))
    : [];
  const listId = `sort-cols-${name}`;

  // block 慣例輸出：asc → 扁平字串；desc → {column, order}
  const sync = (next: SortKey[]) => {
    setDisplay(next.length ? next : [{ column: "", order: "asc" }]);
    const out = next
      .filter((r) => r.column.trim())
      .map((r) => (r.order === "asc" ? r.column.trim() : { column: r.column.trim(), order: "desc" as const }));
    lastExtKey.current = JSON.stringify(out);
    onChange(out);
  };
  const update = (i: number, patch: Partial<SortKey>) =>
    sync(display.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => setDisplay((prev) => [...prev, { column: "", order: "asc" }]);
  const remove = (i: number) => sync(display.filter((_, j) => j !== i));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {display.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "#94A3B8", width: 14, textAlign: "right", flexShrink: 0 }}>{i + 1}.</span>
          <input
            data-testid={`sort-col-${name}-${i}`}
            type="text"
            list={cols.length ? listId : undefined}
            value={row.column}
            onChange={(e) => update(i, { column: e.target.value })}
            disabled={disabled}
            placeholder="排序欄位（如 toolID）"
            style={{ ...commonStyle, borderColor, flex: 1 }}
            autoComplete="off"
          />
          <select
            value={row.order}
            onChange={(e) => update(i, { order: e.target.value as "asc" | "desc" })}
            disabled={disabled}
            style={{ ...commonStyle, borderColor, width: 74, flexShrink: 0 }}
          >
            <option value="asc">升冪</option>
            <option value="desc">降冪</option>
          </select>
          <button
            type="button"
            onClick={() => remove(i)}
            disabled={disabled || display.length === 1}
            title="移除這個排序鍵"
            style={{
              border: "none", background: "none", cursor: "pointer",
              color: "#94A3B8", fontSize: 12, padding: "0 2px", flexShrink: 0,
            }}
          >✕</button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        disabled={disabled}
        style={{
          alignSelf: "flex-start", border: `1px dashed ${borderColor}`,
          background: "none", color: "#64748B", fontSize: 11,
          padding: "3px 10px", borderRadius: 6, cursor: "pointer",
        }}
      >＋ 加排序鍵</button>
      {cols.length > 0 && (
        <datalist id={listId}>
          {cols.map((c) => <option key={c} value={c} />)}
        </datalist>
      )}
    </div>
  );
}
