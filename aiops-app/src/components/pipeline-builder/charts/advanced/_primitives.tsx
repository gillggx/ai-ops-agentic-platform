"use client";

/**
 * Shared UI primitives for Advanced settings components.
 *
 * Layout matches the Simple StyleAdjuster popover (left label, right
 * control) so the two tabs feel consistent.
 *
 * `patch` is the per-card override map. Components don't replace the
 * whole spec — they merge field changes via setPatch({...patch, key:val}).
 * The host page applies `{...baseSpec, ...patch}` to get the live spec.
 */

import * as React from "react";

export interface AdvancedProps {
  /** Read-only — the current chart_spec from the example factory.
   *  Use to display existing values when patch hasn't overridden them. */
  baseSpec: Record<string, unknown>;
  /** Override map. UNDEFINED = use baseSpec value; defined = override. */
  patch: Record<string, unknown>;
  /** Replace the patch (caller spreads to merge). */
  setPatch: (next: Record<string, unknown>) => void;
}

/** Get current effective value (patch overrides baseSpec). */
export function useEffectiveValue<T>(props: AdvancedProps, key: string, fallback: T): T {
  const v = props.patch[key] !== undefined ? props.patch[key] : props.baseSpec[key];
  return (v === undefined ? fallback : v) as T;
}

export function setOverride(props: AdvancedProps, key: string, value: unknown) {
  props.setPatch({ ...props.patch, [key]: value });
}

// ── Row primitives ────────────────────────────────────────────────────

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="pb-style-row">
      <label>{label}</label>
      {children}
    </div>
  );
}

export function ColorRow(props: AdvancedProps & { label: string; field: string; defaultValue?: string }) {
  const v = useEffectiveValue(props, props.field, props.defaultValue ?? "#2563EB") as string;
  return (
    <Row label={props.label}>
      <input
        type="color"
        value={typeof v === "string" ? v : "#2563EB"}
        onChange={(e) => setOverride(props, props.field, e.target.value)}
      />
      <span className="pb-style-val">{v}</span>
    </Row>
  );
}

export function SelectRow<T extends string>({
  label, field, options, defaultValue, ...props
}: AdvancedProps & {
  label: string;
  field: string;
  options: ReadonlyArray<readonly [T, string]>;
  defaultValue: T;
}) {
  const v = useEffectiveValue<T>(props, field, defaultValue);
  return (
    <Row label={label}>
      <select
        value={v}
        onChange={(e) => setOverride(props, field, e.target.value as T)}
      >
        {options.map(([val, lbl]) => (
          <option key={val} value={val}>{lbl}</option>
        ))}
      </select>
    </Row>
  );
}

export function SliderRow({
  label, field, min, max, step, defaultValue, format, ...props
}: AdvancedProps & {
  label: string;
  field: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  format?: (v: number) => string;
}) {
  const v = useEffectiveValue<number>(props, field, defaultValue);
  return (
    <Row label={label}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={v}
        onChange={(e) => setOverride(props, field, Number(e.target.value))}
      />
      <span className="pb-style-val">{format ? format(v) : v}</span>
    </Row>
  );
}

export function ToggleRow({
  label, field, defaultValue, ...props
}: AdvancedProps & {
  label: string;
  field: string;
  defaultValue: boolean;
}) {
  const v = useEffectiveValue<boolean>(props, field, defaultValue);
  return (
    <Row label={label}>
      <button
        type="button"
        className={`pb-style-toggle${v ? " on" : ""}`}
        onClick={() => setOverride(props, field, !v)}
      >
        {v ? "ON" : "OFF"}
      </button>
    </Row>
  );
}

export function SectionHeader({ children }: { children: React.ReactNode }) {
  return <div className="pb-style-h" style={{ marginTop: 8 }}>{children}</div>;
}
