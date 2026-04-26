"use client";

/**
 * PlanRenderer — v1.4 Plan Panel.
 *
 * Renders the agent's live todo list (Claude-Code-style checklist) above
 * the chat. Driven by SSE events:
 *   plan         — declares initial items
 *   plan_update  — flips one item's status / adds a note
 *
 * The agent emits a plan as its first tool call on every new turn; items
 * progress pending → in_progress → done | failed as the agent works.
 *
 * Stays mounted between turns but is reset to a fresh list when a new
 * plan event arrives. Empty plan ⇒ component renders nothing.
 */

import React from "react";

export interface PlanItem {
  id: string;
  title: string;
  status: "pending" | "in_progress" | "done" | "failed";
  note?: string;
}

interface Props {
  items: PlanItem[];
}

const STATUS_GLYPH: Record<PlanItem["status"], string> = {
  pending: "○",
  in_progress: "◐",
  done: "✓",
  failed: "✕",
};

const STATUS_COLOR: Record<PlanItem["status"], string> = {
  pending: "#a0aec0",
  in_progress: "#2b6cb0",
  done: "#38a169",
  failed: "#e53e3e",
};

export function PlanRenderer({ items }: Props) {
  if (!items || items.length === 0) return null;

  const doneCount = items.filter((i) => i.status === "done").length;
  const failedCount = items.filter((i) => i.status === "failed").length;
  const total = items.length;

  return (
    <div style={{
      marginBottom: 4,
      padding: "8px 12px",
      borderRadius: 8,
      border: "1px solid #e2e8f0",
      background: "#f7f8fc",
      fontSize: 12,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 6,
      }}>
        <span style={{ fontWeight: 600, color: "#1a202c" }}>📋 計畫</span>
        <span style={{ fontSize: 10, color: "#718096" }}>
          {doneCount}/{total}{failedCount > 0 ? ` · ${failedCount} 失敗` : ""}
        </span>
      </div>
      <ul style={{
        margin: 0, padding: 0, listStyle: "none",
        display: "flex", flexDirection: "column", gap: 3,
      }}>
        {items.map((item) => (
          <li
            key={item.id}
            style={{
              display: "flex", alignItems: "flex-start", gap: 6,
              color: STATUS_COLOR[item.status],
              fontWeight: item.status === "in_progress" ? 600 : 400,
              opacity: item.status === "done" ? 0.65 : 1,
            }}
          >
            <span style={{
              minWidth: 14, textAlign: "center",
              animation: item.status === "in_progress" ? "pb-pulse 1.5s ease-in-out infinite" : undefined,
            }}>
              {STATUS_GLYPH[item.status]}
            </span>
            <span style={{
              flex: 1,
              textDecoration: item.status === "done" ? "line-through" : "none",
              color: item.status === "done" ? "#718096" : undefined,
            }}>
              {item.title}
              {item.note && (
                <span style={{
                  marginLeft: 6, fontSize: 10,
                  color: "#a0aec0", fontWeight: 400,
                }}>
                  — {item.note}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      <style>{`
        @keyframes pb-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
