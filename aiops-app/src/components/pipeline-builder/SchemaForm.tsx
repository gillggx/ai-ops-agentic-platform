"use client";

/**
 * SchemaForm — minimal JSON-schema-driven form.
 *
 * Widget resolution order for a string field:
 *   1. `enum`               → <select>
 *   2. `x-column-source`    → column picker (select from upstream columns, with fallback)
 *   3. `x-suggestions`      → <input> + <datalist>
 *   4. otherwise            → plain <input type="text">
 */

import { useEffect, useMemo, useState } from "react";
import { fetchSuggestions } from "@/lib/pipeline-builder/api";
import type { JsonSchemaProperty, ParamSchema } from "@/lib/pipeline-builder/types";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { ColumnsByPort } from "@/context/pipeline-builder/useUpstreamColumns";
import { FieldsEditor } from "@/components/pipeline-builder/FieldsEditor";


/** Module-level cache so we don't re-fetch suggestions for every keystroke */
const _suggestionCache: Record<string, string[] | Promise<string[]>> = {};

function useSuggestions(source: string | undefined): string[] {
  const [items, setItems] = useState<string[]>(() => {
    if (!source) return [];
    const cached = _suggestionCache[source];
    return Array.isArray(cached) ? cached : [];
  });

  useEffect(() => {
    if (!source) return;
    const cached = _suggestionCache[source];
    if (Array.isArray(cached)) {
      setItems(cached);
      return;
    }
    if (cached instanceof Promise) {
      cached.then(setItems).catch(() => setItems([]));
      return;
    }
    const p = fetchSuggestions(source).then((list) => {
      _suggestionCache[source] = list;
      return list;
    });
    _suggestionCache[source] = p;
    p.then(setItems).catch(() => setItems([]));
  }, [source]);

  return items;
}

interface Props {
  schema: ParamSchema;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
  /** Upstream output columns, indexed by this node's input port name. */
  upstreamColumns?: ColumnsByPort;
  /** Whether upstream columns are still being fetched (shows a small hint). */
  upstreamLoading?: boolean;
  /** Per-port error messages from upstream preview attempt. */
  upstreamErrors?: Record<string, string>;
}

export default function SchemaForm({
  schema,
  values,
  onChange,
  disabled,
  upstreamColumns,
  upstreamLoading,
  upstreamErrors,
}: Props) {
  const fields = useMemo(() => {
    if (!schema?.properties) return [];
    return Object.entries(schema.properties);
  }, [schema]);

  if (fields.length === 0) {
    return <div style={{ color: "#94A3B8", fontSize: 11 }}>此積木無參數</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {fields.map(([key, prop]) => (
        <FormField
          key={key}
          name={key}
          prop={prop}
          required={(schema.required ?? []).includes(key)}
          value={values[key]}
          onChange={(v) => onChange(key, v)}
          disabled={disabled}
          upstreamColumns={upstreamColumns}
          upstreamLoading={upstreamLoading}
          upstreamErrors={upstreamErrors}
        />
      ))}
    </div>
  );
}

function FormField({
  name,
  prop,
  required,
  value,
  onChange,
  disabled,
  upstreamColumns,
  upstreamLoading,
  upstreamErrors,
}: {
  name: string;
  prop: JsonSchemaProperty;
  required: boolean;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  upstreamColumns?: ColumnsByPort;
  upstreamLoading?: boolean;
  upstreamErrors?: Record<string, string>;
}) {
  const isMissing = required && (value === undefined || value === null || value === "");
  const labelColor = isMissing ? "#B91C1C" : "#475569";
  const borderColor = isMissing ? "#FCA5A5" : "#CBD5E1";
  const label = prop.title ?? name;

  // Phase 4-B0: if param value is a "$var" reference → show bound chip instead of raw widget
  const refName = typeof value === "string" && value.startsWith("$") ? value.slice(1) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 11, color: labelColor, letterSpacing: "0.02em", display: "flex", alignItems: "center", gap: 4 }}>
        <span>
          {label}
          {required && <span style={{ color: "#B91C1C" }}> *</span>}
          <span style={{ color: "#CBD5E1", marginLeft: 6, fontWeight: 400 }}>{name}</span>
        </span>
        <span style={{ flex: 1 }} />
        <ParamBindMenu
          paramName={name}
          paramType={prop.type}
          currentValue={value}
          boundRef={refName}
          onBind={(inputName) => onChange(`$${inputName}`)}
          onUnbind={() => onChange(undefined)}
          disabled={disabled}
        />
      </label>
      {refName ? (
        <div
          data-testid={`param-bound-${name}`}
          style={{
            padding: "4px 10px",
            background: "var(--pl, #EEF2FF)",
            border: "1px solid var(--pl, #C7D2FE)",
            borderRadius: 4,
            fontSize: 12,
            color: "#3730A3",
            fontFamily: "ui-monospace, monospace",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span>${refName}</span>
          <span style={{ fontSize: 10, color: "var(--p, #6366F1)" }}>← 綁定 pipeline input</span>
        </div>
      ) : (
        renderWidget({
          name,
          prop,
          value,
          onChange,
          disabled,
          borderColor,
          upstreamColumns,
          upstreamLoading,
          upstreamErrors,
        })
      )}
    </div>
  );
}

/** Small menu button next to each field label — bind / unbind pipeline input reference. */
function ParamBindMenu({
  paramName,
  paramType,
  currentValue,
  boundRef,
  onBind,
  onUnbind,
  disabled,
}: {
  paramName: string;
  paramType?: string;
  currentValue: unknown;
  boundRef: string | null;
  onBind: (inputName: string) => void;
  onUnbind: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { state, actions } = useBuilder();
  const inputs = state.pipeline.inputs ?? [];

  if (disabled) return null;

  if (boundRef) {
    return (
      <button
        data-testid={`param-unbind-${paramName}`}
        onClick={onUnbind}
        title="解除綁定"
        style={menuTriggerStyle}
      >
        ↺ 解除
      </button>
    );
  }

  const handleCreateAndBind = () => {
    // Auto-declare an input from current value (if any), then bind.
    const newName = paramName;
    const already = inputs.some((i) => i.name === newName);
    if (!already) {
      const mappedType = paramType === "integer" ? "integer" : paramType === "number" ? "number" : paramType === "boolean" ? "boolean" : "string";
      actions.declareInput({
        name: newName,
        type: mappedType as "string" | "integer" | "number" | "boolean",
        required: false,
        example: typeof currentValue === "string" || typeof currentValue === "number" ? currentValue : undefined,
      });
    }
    onBind(newName);
    setOpen(false);
  };

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        data-testid={`param-bind-${paramName}`}
        onClick={() => setOpen((o) => !o)}
        title="綁定 pipeline input"
        style={menuTriggerStyle}
      >
        → 變數
      </button>
      {open && (
        <div
          role="menu"
          onMouseLeave={() => setOpen(false)}
          style={{
            position: "absolute",
            right: 0,
            top: "100%",
            marginTop: 4,
            background: "#fff",
            border: "1px solid #E2E8F0",
            borderRadius: 4,
            boxShadow: "0 4px 12px rgba(15,23,42,0.1)",
            zIndex: 20,
            minWidth: 180,
            fontSize: 11,
          }}
        >
          <div style={menuHeader}>選擇已宣告 input</div>
          {inputs.length === 0 && (
            <div style={{ padding: "6px 10px", color: "#94A3B8" }}>（尚未宣告）</div>
          )}
          {inputs.map((inp) => (
            <button
              key={inp.name}
              data-testid={`param-bind-choose-${paramName}-${inp.name}`}
              onClick={() => { onBind(inp.name); setOpen(false); }}
              style={menuItemStyle}
            >
              <code style={{ color: "#3730A3", fontFamily: "ui-monospace, monospace" }}>${inp.name}</code>
              <span style={{ color: "#94A3B8", marginLeft: 6 }}>({inp.type})</span>
            </button>
          ))}
          <div style={{ borderTop: "1px solid #F1F5F9" }} />
          <button
            data-testid={`param-bind-new-${paramName}`}
            onClick={handleCreateAndBind}
            style={{ ...menuItemStyle, color: "#166534" }}
          >
            ＋ 從目前值新增 <code style={{ fontFamily: "ui-monospace, monospace" }}>${paramName}</code>
          </button>
        </div>
      )}
    </div>
  );
}

const menuTriggerStyle: React.CSSProperties = {
  background: "none",
  border: "1px solid #E2E8F0",
  padding: "1px 6px",
  fontSize: 9,
  color: "#64748B",
  cursor: "pointer",
  borderRadius: 10,
  letterSpacing: "0.03em",
};
const menuHeader: React.CSSProperties = {
  padding: "6px 10px",
  fontSize: 9,
  color: "#94A3B8",
  letterSpacing: "0.05em",
  textTransform: "uppercase",
  fontWeight: 600,
  borderBottom: "1px solid #F1F5F9",
};
const menuItemStyle: React.CSSProperties = {
  width: "100%",
  textAlign: "left",
  padding: "5px 10px",
  background: "none",
  border: "none",
  cursor: "pointer",
  fontSize: 11,
  color: "#334155",
};

function renderWidget({
  name,
  prop,
  value,
  onChange,
  disabled,
  borderColor,
  upstreamColumns,
  upstreamLoading,
  upstreamErrors,
}: {
  name: string;
  prop: JsonSchemaProperty;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  borderColor: string;
  upstreamColumns?: ColumnsByPort;
  upstreamLoading?: boolean;
  upstreamErrors?: Record<string, string>;
}) {
  const commonStyle: React.CSSProperties = {
    width: "100%",
    padding: "5px 8px",
    fontSize: 12,
    border: `1px solid ${borderColor}`,
    borderRadius: 3,
    background: disabled ? "#F1F5F9" : "#fff",
    boxSizing: "border-box",
    outline: "none",
  };

  // 1. Enum → select (with "— 全部 —" if empty string is a valid choice)
  if (prop.enum && prop.enum.length > 0) {
    const hasEmptyOption = prop.enum.some((o) => o === "");
    const optionsExcludingEmpty = prop.enum.filter((o) => o !== "");
    return (
      <select
        style={commonStyle}
        value={(value as string | number | undefined) ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? undefined : v);
        }}
        disabled={disabled}
      >
        {hasEmptyOption ? (
          <option value="">— 全部 —</option>
        ) : (
          <option value="" disabled>
            — 請選擇 —
          </option>
        )}
        {optionsExcludingEmpty.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    );
  }

  // 2. x-column-source → column picker from upstream
  if (prop["x-column-source"]) {
    return (
      <ColumnPicker
        name={name}
        prop={prop}
        value={value}
        onChange={onChange}
        disabled={disabled}
        borderColor={borderColor}
        commonStyle={commonStyle}
        upstreamColumns={upstreamColumns}
        upstreamLoading={upstreamLoading}
        upstreamErrors={upstreamErrors}
      />
    );
  }

  // 2b. fields editor → guided repeating-row editor for array<{path, as}>
  //     (Fix 5: block_select.fields was unfillable via the generic array widget).
  //     Trigger on the explicit marker OR the shape (array of objects with a
  //     `path` property) — the latter works without the pb_blocks DB carrying
  //     the marker (frontend param_schema comes from the DB, not seed.py).
  const isPathFieldsArray =
    prop.type === "array" &&
    prop.items?.type === "object" &&
    !!prop.items?.properties?.path;
  if (prop["x-fields-editor"] || isPathFieldsArray) {
    return (
      <FieldsEditor
        name={name}
        value={value}
        onChange={onChange}
        disabled={disabled}
        borderColor={borderColor}
        commonStyle={commonStyle}
        upstreamColumns={upstreamColumns}
      />
    );
  }

  switch (prop.type) {
    case "boolean":
      return (
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            disabled={disabled}
          />
          <span style={{ fontSize: 11, color: "#94A3B8" }}>{name}</span>
        </label>
      );
    case "integer":
      return (
        <input
          type="number"
          step={1}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "") onChange(undefined);
            else onChange(parseInt(v, 10));
          }}
          disabled={disabled}
          style={commonStyle}
        />
      );
    case "number":
      return (
        <input
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "") onChange(undefined);
            else onChange(parseFloat(v));
          }}
          disabled={disabled}
          style={commonStyle}
        />
      );
    case "array":
      return (
        <input
          type="text"
          value={Array.isArray(value) ? value.join(", ") : ""}
          onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          disabled={disabled}
          placeholder="逗號分隔"
          style={commonStyle}
        />
      );
    case "string":
    default:
      return <StringInputWithSuggestions prop={prop} value={value} name={name} onChange={onChange} disabled={disabled} commonStyle={commonStyle} />;
  }
}

function ColumnPicker({
  name,
  prop,
  value,
  onChange,
  disabled,
  borderColor,
  commonStyle,
  upstreamColumns,
  upstreamLoading,
  upstreamErrors,
}: {
  name: string;
  prop: JsonSchemaProperty;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  borderColor: string;
  commonStyle: React.CSSProperties;
  upstreamColumns?: ColumnsByPort;
  upstreamLoading?: boolean;
  upstreamErrors?: Record<string, string>;
}) {
  const { actions } = useBuilder();
  const source = prop["x-column-source"] ?? "";
  // Source formats:
  //   "input.data"         → single port
  //   "input.left+right"   → union of two ports (block_join)
  const portsSpec = source.replace(/^input\./, "");
  const portList = portsSpec.split("+").filter(Boolean);

  const columns = useMemo(() => {
    if (!upstreamColumns) return [] as string[];
    if (portList.length === 1) return upstreamColumns[portList[0]] ?? [];
    // multi-port: intersection of columns
    const arrays = portList.map((p) => new Set(upstreamColumns[p] ?? []));
    if (arrays.length === 0) return [];
    const first = Array.from(arrays[0]);
    return first.filter((c) => arrays.every((s) => s.has(c)));
  }, [upstreamColumns, portList]);

  const portErr = portList
    .map((p) => upstreamErrors?.[p])
    .filter((x): x is string => !!x)
    .join("; ");

  const currentValue = value === undefined || value === null ? "" : String(value);
  const listId = `col-list-${name}`;
  const hasCols = columns.length > 0;

  // Note: we do NOT clear the focus target on blur — if we did, clicking a
  // preview header (which blurs the picker) would clear the target before the
  // click handler could read it. The target is instead replaced when another
  // column-picker field gets focus.
  const registerFocus = () => actions.setColumnTarget(name);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {/* Searchable combobox: type-to-filter over upstream columns via a native
          <datalist>, but still accepts a custom column name (free text). Native
          datalist gives the filter dropdown with zero extra state — needed
          because flat-mode (nested=false) tables expose 200-300 columns and a
          plain <select> (a) was capped at 30 upstream and (b) is unusable
          without search even when uncapped. */}
      <input
        data-testid={`column-picker-${name}`}
        type="text"
        list={hasCols ? listId : undefined}
        value={currentValue}
        onChange={(e) => onChange(e.target.value || undefined)}
        onFocus={registerFocus}
        disabled={disabled}
        style={{ ...commonStyle, borderColor }}
        placeholder={hasCols ? "輸入以搜尋欄位，或手動輸入" : "手動輸入欄位名"}
        autoComplete="off"
      />
      {hasCols && (
        <datalist id={listId}>
          {columns.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      )}

      {/* hint line */}
      <div style={{ fontSize: 10, color: "#94A3B8", lineHeight: 1.3 }}>
        {upstreamLoading && <>⏳ 載入上游欄位中…</>}
        {!upstreamLoading && hasCols && (
          <>✓ 從上游 <code style={codeStyle}>{portsSpec}</code> 推論出 {columns.length} 個欄位；輸入即時搜尋，或點 Preview 欄位名自動填入</>
        )}
        {!upstreamLoading && !hasCols && !portErr && (
          <>⚠️ 上游尚無資料。請先連線或手動輸入欄位名</>
        )}
        {!upstreamLoading && portErr && (
          <span style={{ color: "#B91C1C" }}>⚠️ 上游 preview 失敗 — 降級為手動輸入</span>
        )}
      </div>
    </div>
  );
}


function StringInputWithSuggestions({
  prop,
  value,
  name,
  onChange,
  disabled,
  commonStyle,
}: {
  prop: JsonSchemaProperty;
  value: unknown;
  name: string;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  commonStyle: React.CSSProperties;
}) {
  const source = prop["x-suggestions"];
  const suggestions = useSuggestions(source);
  const listId = source ? `pb-datalist-${source}` : undefined;
  return (
    <>
      <input
        data-testid={`field-${name}`}
        type="text"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value || undefined)}
        disabled={disabled}
        list={listId}
        style={commonStyle}
        autoComplete="off"
      />
      {listId && (
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </>
  );
}

const codeStyle: React.CSSProperties = {
  background: "#F1F5F9",
  padding: "0 4px",
  borderRadius: 2,
  fontSize: 10,
  color: "#334155",
};
