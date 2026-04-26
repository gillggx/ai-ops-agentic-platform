"use client";

/**
 * OpsConsole — collapsible accumulator for the Glass Box build ops
 * (add_node / connect / rename_node / set_param / preview / validate /
 * finish). Default collapsed because most users only want to see the
 * plan progress + final result; expand reveals the per-op trail.
 */

import { useState } from "react";

export interface GlassOpEntry {
  id: number;
  op: string;
  label: string;
  detail?: string;
  ts: number;
  isError?: boolean;
}

interface Props {
  ops: GlassOpEntry[];
}

export default function OpsConsole({ ops }: Props) {
  const [open, setOpen] = useState(false);
  if (ops.length === 0) return null;

  return (
    <div
      style={{
        marginBottom: 4,
        background: "#F8FAFC",
        border: "1px solid #E2E8F0",
        borderRadius: 8,
        fontSize: 12,
      }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          textAlign: "left",
          padding: "7px 10px",
          background: "transparent",
          border: "none",
          color: "#475569",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontWeight: 500,
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              display: "inline-block",
              transition: "transform 0.15s",
              transform: open ? "rotate(90deg)" : "rotate(0deg)",
              fontSize: 10,
              color: "#94A3B8",
            }}
          >
            ▶
          </span>
          建構過程（{ops.length} ops）
        </span>
        <span style={{ color: "#94A3B8", fontSize: 11 }}>
          {open ? "收合" : "展開細節"}
        </span>
      </button>
      {open && (
        <div
          style={{
            padding: "0 10px 8px",
            borderTop: "1px solid #E2E8F0",
            color: "#64748B",
            lineHeight: 1.7,
            maxHeight: 200,
            overflowY: "auto",
          }}
        >
          {ops.map((o) => (
            <div
              key={o.id}
              style={{
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: 11,
                color: o.isError ? "#B91C1C" : "#475569",
                paddingTop: 4,
              }}
            >
              <span style={{ color: "#94A3B8", marginRight: 8 }}>
                {new Date(o.ts).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span style={{ fontWeight: 600 }}>{o.label}</span>
              {o.detail && <span style={{ marginLeft: 6 }}>{o.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
