"use client";

/**
 * Phase 5-UX-5: Pipeline Builder Copilot — Patch Proposal Card.
 *
 * Shown in the chat when Agent proposes structural changes to the current
 * pipeline (insert / update / delete node, connect edge). User clicks
 * "套用到 Canvas" to commit or "不用了" to dismiss. Applying uses BuilderContext
 * actions directly (no further LLM roundtrip).
 */

import { useState } from "react";

export type PatchOp =
  | "insert_after" | "insert_before" | "update_params" | "delete_node" | "connect_edge";

export interface PipelinePatch {
  op: PatchOp;
  anchor_node_id?: string;
  node_id?: string;
  new_node_id?: string;
  block_id?: string;
  block_version?: string;
  params?: Record<string, unknown>;
  from?: { node: string; port: string };
  to?: { node: string; port: string };
}

export interface PbPatchProposalData {
  type: "pb_patch_proposal";
  reason?: string;
  patches: PipelinePatch[];
}

interface Props {
  proposal: PbPatchProposalData;
  onApply?: (patches: PipelinePatch[]) => Promise<void> | void;
  onReject?: () => void;
}

export default function PbPatchProposalCard({ proposal, onApply, onReject }: Props) {
  const [state, setState] = useState<"pending" | "applying" | "applied" | "rejected">("pending");
  const [error, setError] = useState<string | null>(null);

  async function handleApply() {
    if (!onApply) return;
    setState("applying");
    try {
      await onApply(proposal.patches);
      setState("applied");
    } catch (e) {
      setState("pending");
      setError((e as Error).message);
    }
  }

  return (
    <div
      style={{
        width: "100%",
        border: "1px solid var(--pl, #c7d2fe)",
        borderRadius: 8,
        background: "var(--pl, #eef2ff)",
        overflow: "hidden",
        fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
        marginTop: 4,
      }}
    >
      {/* Header */}
      <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--pl, #c7d2fe)", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 14 }}>✦</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#3730a3", flex: 1 }}>
          建議動作 · {proposal.patches.length} patch{proposal.patches.length > 1 ? "es" : ""}
        </span>
      </div>

      {/* Reason */}
      {proposal.reason && (
        <div style={{ padding: "8px 12px", fontSize: 12, color: "#312e81", lineHeight: 1.5 }}>
          {proposal.reason}
        </div>
      )}

      {/* Patches */}
      <div style={{ padding: "4px 12px 10px" }}>
        {proposal.patches.map((p, i) => (
          <PatchRow key={i} patch={p} />
        ))}
      </div>

      {/* Actions */}
      <div style={{ padding: "8px 12px", display: "flex", gap: 8, borderTop: "1px solid var(--pl, #c7d2fe)", background: "#f5f3ff" }}>
        {state === "applied" && (
          <span style={{ fontSize: 12, color: "#166534", fontWeight: 600 }}>✓ 已套用至 Canvas</span>
        )}
        {state === "rejected" && (
          <span style={{ fontSize: 12, color: "#64748b" }}>已忽略</span>
        )}
        {(state === "pending" || state === "applying") && (
          <>
            <button
              onClick={handleApply}
              disabled={state === "applying" || !onApply}
              style={{
                padding: "5px 12px",
                fontSize: 11,
                fontWeight: 600,
                background: "var(--p, #4338ca)",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                cursor: state === "applying" ? "wait" : "pointer",
              }}
            >
              {state === "applying" ? "套用中…" : "套用到 Canvas"}
            </button>
            <button
              onClick={() => { setState("rejected"); onReject?.(); }}
              style={{
                padding: "5px 12px",
                fontSize: 11,
                background: "#fff",
                color: "#4a5568",
                border: "1px solid #cbd5e0",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              不用了
            </button>
          </>
        )}
        {error && <span style={{ fontSize: 11, color: "#dc2626", marginLeft: "auto" }}>{error}</span>}
      </div>
    </div>
  );
}

function PatchRow({ patch }: { patch: PipelinePatch }) {
  const opLabel: Record<PatchOp, { icon: string; label: string; color: string }> = {
    insert_after: { icon: "➕", label: "加入 (after)", color: "#166534" },
    insert_before: { icon: "➕", label: "加入 (before)", color: "#166534" },
    update_params: { icon: "✏️", label: "更新參數", color: "#92400e" },
    delete_node: { icon: "🗑", label: "刪除", color: "#b91c1c" },
    connect_edge: { icon: "↔", label: "新增邊", color: "var(--p, #4338ca)" },
  };
  const meta = opLabel[patch.op] ?? { icon: "•", label: patch.op, color: "#64748b" };

  return (
    <div
      style={{
        padding: "6px 8px",
        margin: "4px 0",
        background: "#fff",
        border: "1px solid var(--pl, #e0e7ff)",
        borderRadius: 4,
        fontSize: 11,
        color: "#1e293b",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
        <span>{meta.icon}</span>
        <span style={{ fontWeight: 600, color: meta.color }}>{meta.label}</span>
        {patch.block_id && (
          <code style={{ background: "#f1f5f9", padding: "1px 5px", borderRadius: 3, fontSize: 10 }}>
            {patch.block_id}
          </code>
        )}
        {patch.node_id && <code style={{ fontSize: 10, color: "#64748b" }}>#{patch.node_id}</code>}
        {patch.anchor_node_id && <code style={{ fontSize: 10, color: "#64748b" }}>after #{patch.anchor_node_id}</code>}
      </div>
      {patch.params && Object.keys(patch.params).length > 0 && (
        <div style={{ fontSize: 10, color: "#475569", marginLeft: 20, fontFamily: "monospace" }}>
          {Object.entries(patch.params).slice(0, 5).map(([k, v]) => (
            <div key={k}>{k}: {JSON.stringify(v)}</div>
          ))}
        </div>
      )}
      {patch.from && patch.to && (
        <div style={{ fontSize: 10, color: "#475569", marginLeft: 20, fontFamily: "monospace" }}>
          {patch.from.node}.{patch.from.port} → {patch.to.node}.{patch.to.port}
        </div>
      )}
    </div>
  );
}
