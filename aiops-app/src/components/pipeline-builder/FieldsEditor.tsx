"use client";

/**
 * FieldsEditor (Fix 5, 2026-06-14) — guided editor for an `array<{path, as}>`
 * param (block_select.fields). The generic SchemaForm array widget only handles
 * comma-separated scalars, so block_select was unfillable by hand. This renders
 * one row per selected field: a path picker (datalist of upstream top-level
 * columns + free text for nested `A.b.c` paths) + an `as` alias + remove, plus
 * an "add field" button. value stays a clean `[{path, as?}]` array.
 */
import React from "react";

import type { ColumnsByPort } from "@/context/pipeline-builder/useUpstreamColumns";

type Field = { path: string; as?: string };

export function FieldsEditor({
  name,
  value,
  onChange,
  disabled,
  borderColor,
  commonStyle,
  upstreamColumns,
}: {
  name: string;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  borderColor: string;
  commonStyle: React.CSSProperties;
  upstreamColumns?: ColumnsByPort;
}) {
  // Tolerate garbage / non-array values from older pipelines without crashing.
  const rows: Field[] = Array.isArray(value)
    ? (value as unknown[]).map((r) => {
        const o = (r ?? {}) as Record<string, unknown>;
        return {
          path: String(o.path ?? ""),
          as: o.as != null ? String(o.as) : undefined,
        };
      })
    : [];
  const display: Field[] = rows.length ? rows : [{ path: "", as: "" }];

  // union of all upstream ports' top-level columns → path datalist
  const cols = upstreamColumns
    ? Array.from(new Set(Object.values(upstreamColumns).flat()))
    : [];
  const listId = `fields-cols-${name}`;

  const emit = (next: Field[]) => onChange(next);
  const update = (i: number, patch: Partial<Field>) =>
    emit(display.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => emit([...display, { path: "", as: "" }]);
  const remove = (i: number) => emit(display.filter((_, j) => j !== i));

  const rowStyle: React.CSSProperties = { display: "flex", gap: 4, alignItems: "center" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {display.map((row, i) => (
        <div key={i} style={rowStyle}>
          <input
            data-testid={`fields-path-${name}-${i}`}
            type="text"
            list={cols.length ? listId : undefined}
            value={row.path}
            onChange={(e) => update(i, { path: e.target.value })}
            disabled={disabled}
            placeholder="path（來源欄位，可巢狀 A.b.c）"
            style={{ ...commonStyle, borderColor, flex: 2 }}
            autoComplete="off"
          />
          <span style={{ fontSize: 11, color: "#94A3B8" }}>as</span>
          <input
            data-testid={`fields-as-${name}-${i}`}
            type="text"
            value={row.as ?? ""}
            onChange={(e) => update(i, { as: e.target.value || undefined })}
            disabled={disabled}
            placeholder="別名（預設 = path 末段）"
            style={{ ...commonStyle, borderColor, flex: 1 }}
          />
          <button
            type="button"
            onClick={() => remove(i)}
            disabled={disabled}
            title="刪除這列"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              color: "#B91C1C",
              fontSize: 15,
              lineHeight: 1,
              padding: "0 4px",
            }}
          >
            ×
          </button>
        </div>
      ))}

      {cols.length > 0 && (
        <datalist id={listId}>
          {cols.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      )}

      <button
        type="button"
        onClick={add}
        disabled={disabled}
        style={{
          alignSelf: "flex-start",
          marginTop: 2,
          fontSize: 11,
          padding: "3px 8px",
          border: `1px dashed ${borderColor}`,
          borderRadius: 3,
          background: "#fff",
          cursor: "pointer",
          color: "#3730A3",
        }}
      >
        + 新增欄位
      </button>

      <div style={{ fontSize: 10, color: "#94A3B8", lineHeight: 1.3 }}>
        {cols.length > 0 ? (
          <>
            ✓ 上游有 {cols.length} 個頂層欄位可選；巢狀路徑直接打{" "}
            <code style={{ fontFamily: "ui-monospace, monospace" }}>A.b.c</code>
          </>
        ) : (
          <>
            每列一個輸出欄位：path（來源，可巢狀{" "}
            <code style={{ fontFamily: "ui-monospace, monospace" }}>A.b.c</code>）+ as（別名）
          </>
        )}
      </div>
    </div>
  );
}
