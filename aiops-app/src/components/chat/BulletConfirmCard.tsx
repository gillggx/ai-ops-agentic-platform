/**
 * BulletConfirmCard — v19 chat intent confirmation UI.
 *
 * Renders when chat SSE stream emits `pb_intent_confirm`. Shows the
 * model's restated intent as bullets + optional preview chart, lets the
 * user confirm / reject / edit each, then POSTs to /api/agent/chat/
 * intent-respond which resumes the paused build.
 *
 * Dark theme to match ChatPanel.
 */
"use client";

import * as React from "react";
import ChartRenderer from "@/components/pipeline-builder/ChartRenderer";

export interface IntentBullet {
  id: string;
  text: string;
  terminal_block?: string;
  preview_chart_spec?: Record<string, unknown>;
  options?: Array<{ value: string; label: string }>;
}

interface Props {
  /** Chat session id (when used in chat) OR build session id (Skill Builder). */
  chatSessionId: string;
  bullets: IntentBullet[];
  tooVagueReason?: string;
  /** v19 refactor (2026-05-14): parent drives the SSE so existing event
   *  handlers (pb_glass_op → canvas apply, pb_glass_done → message, etc.)
   *  run through the SAME consumeSSE path /chat uses. Card only collects
   *  confirmations + delegates. Parent calls back with final status. */
  onConfirm: (
    confirmations: Record<string, { action: Action; edit_text?: string }>,
  ) => Promise<"confirmed" | "refused" | "error">;
}

type Action = "ok" | "reject" | "edit";

export function BulletConfirmCard(props: Props) {
  const { bullets, tooVagueReason, onConfirm } = props;
  const [actions, setActions] = React.useState<Record<string, Action>>(
    Object.fromEntries(bullets.map((b) => [b.id, "ok"]))
  );
  const [edits, setEdits] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string>("");

  async function submit(actionOverrideAll?: Action) {
    setBusy(true);
    setError("");
    const confirmations: Record<string, { action: Action; edit_text?: string }> = {};
    for (const b of bullets) {
      const a = actionOverrideAll ?? actions[b.id] ?? "ok";
      confirmations[b.id] = { action: a };
      if (a === "edit" && edits[b.id]) {
        confirmations[b.id].edit_text = edits[b.id];
      }
    }
    try {
      // Parent does the POST + SSE consumption so events flow through
      // the existing /chat event-handler pipeline (canvas-apply etc.).
      await onConfirm(confirmations);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const allRejected = Object.values(actions).every((a) => a === "reject");

  return (
    <div style={{
      background: "#1a202c",
      border: "1px solid #2d3748",
      borderLeft: "3px solid #3182ce",
      borderRadius: 8,
      padding: 14,
      width: "100%",
    }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: "#90cdf4",
        letterSpacing: 0.4, marginBottom: 6,
      }}>
        🧠 我理解的需求 — 請確認
      </div>
      {tooVagueReason && (
        <div style={{
          fontSize: 11, color: "#f6ad55", marginBottom: 8,
          padding: "6px 8px", background: "#2d2415", borderRadius: 4,
        }}>
          ⚠ 上次嘗試太模糊：{tooVagueReason.slice(0, 200)}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {bullets.map((b, i) => (
          <div key={b.id} style={{
            background: "#0d1117",
            border: "1px solid #2d3748",
            borderRadius: 6,
            padding: "8px 10px",
            fontSize: 12,
            color: "#e2e8f0",
          }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
              <span style={{
                fontFamily: "monospace", fontSize: 10, color: "#4a5568",
                minWidth: 22,
              }}>
                {b.id}
              </span>
              <span style={{ flex: 1, lineHeight: 1.5 }}>{b.text}</span>
              {b.terminal_block && (
                <span style={{
                  fontSize: 10, padding: "1px 6px",
                  background: "#1a365d", color: "#90cdf4",
                  borderRadius: 4, fontFamily: "monospace",
                }}>
                  → {b.terminal_block}
                </span>
              )}
            </div>
            {/* Per-bullet action row */}
            <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
              {(["ok", "reject", "edit"] as Action[]).map((a) => (
                <button
                  key={a}
                  onClick={() => setActions((p) => ({ ...p, [b.id]: a }))}
                  disabled={busy}
                  style={{
                    fontSize: 10,
                    padding: "2px 8px",
                    background: actions[b.id] === a
                      ? (a === "ok" ? "#22543d" : a === "reject" ? "#742a2a" : "#744210")
                      : "#0d1117",
                    color: actions[b.id] === a
                      ? (a === "ok" ? "#9ae6b4" : a === "reject" ? "#feb2b2" : "#fbd38d")
                      : "#718096",
                    border: `1px solid ${actions[b.id] === a
                      ? (a === "ok" ? "#22543d" : a === "reject" ? "#742a2a" : "#744210")
                      : "#2d3748"}`,
                    borderRadius: 3,
                    cursor: busy ? "not-allowed" : "pointer",
                    fontWeight: 500,
                  }}
                >
                  {a === "ok" ? "✓ OK" : a === "reject" ? "✗ Reject" : "✏ Edit"}
                </button>
              ))}
            </div>
            {actions[b.id] === "edit" && (
              <input
                value={edits[b.id] || ""}
                onChange={(e) => setEdits((p) => ({ ...p, [b.id]: e.target.value }))}
                placeholder="改寫成你要的描述..."
                style={{
                  width: "100%",
                  marginTop: 6,
                  padding: "4px 8px",
                  background: "#0d1117",
                  border: "1px solid #2d3748",
                  borderRadius: 3,
                  color: "#e2e8f0",
                  fontSize: 11,
                  fontFamily: "inherit",
                  boxSizing: "border-box",
                }}
              />
            )}
            {b.preview_chart_spec && (
              <details style={{ marginTop: 8 }}>
                <summary style={{
                  fontSize: 10, color: "#718096", cursor: "pointer",
                  listStyle: "none",
                }}>
                  ▸ preview chart
                </summary>
                <div style={{
                  marginTop: 6, padding: 6,
                  background: "#fff", borderRadius: 4,
                }}>
                  <ChartRenderer spec={b.preview_chart_spec as Parameters<typeof ChartRenderer>[0]["spec"]} />
                </div>
              </details>
            )}
            {i < bullets.length - 1 && i % 2 === 0 && i > 0 && (
              <div style={{ height: 1, background: "#2d3748", margin: "8px 0" }} />
            )}
          </div>
        ))}
      </div>

      <div style={{
        display: "flex", gap: 8, marginTop: 12, paddingTop: 12,
        borderTop: "1px solid #2d3748",
      }}>
        <button
          onClick={() => submit("ok")}
          disabled={busy}
          style={{
            flex: 1,
            padding: "8px",
            background: "#22543d",
            color: "#9ae6b4",
            border: "none",
            borderRadius: 4,
            fontSize: 12,
            fontWeight: 600,
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "⟳ 處理中..." : "✓ 全部確認，開始建構"}
        </button>
        <button
          onClick={() => submit("reject")}
          disabled={busy || allRejected}
          style={{
            flex: 1,
            padding: "8px",
            background: "transparent",
            color: "#feb2b2",
            border: "1px solid #742a2a",
            borderRadius: 4,
            fontSize: 12,
            fontWeight: 600,
            cursor: busy ? "wait" : "pointer",
            opacity: busy ? 0.5 : 1,
          }}
        >
          ✗ 重新描述
        </button>
      </div>
      {error && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#f56565" }}>
          {error}
        </div>
      )}
    </div>
  );
}
