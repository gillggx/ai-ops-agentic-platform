"use client";

/**
 * Phase 11 v4 — sticky banner shown when Pipeline Builder is launched
 * from inside a Skill (Skill → Translate → Builder). Persists the
 * skill embed context across the /new → /[id] navigation that happens
 * on first save by stashing the context in sessionStorage.
 *
 * The "Done — bind to Skill" CTA POSTs the current pipelineId back to
 * /api/skill-documents/{slug}/bind-pipeline, then closes the tab.
 */

import { useCallback, useEffect, useState } from "react";

const SS_KEY = "pb:skill_embed_ctx";

export interface SkillEmbedCtx {
  skill_slug: string;
  skill_doc_id: number;
  slot: string;                    // confirm | step:NEW | step:s1 | ...
  instruction: string;
  trigger_type: "event" | "schedule";
  trigger_event?: string;
  target_kind?: "all" | "tools" | "stations";
  target_ids?: string[];
  /** Inputs we seeded into the pipeline at start time. */
  seeded_input_names?: string[];
}

export function readSkillCtx(): SkillEmbedCtx | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(SS_KEY);
    return raw ? (JSON.parse(raw) as SkillEmbedCtx) : null;
  } catch {
    return null;
  }
}

export function writeSkillCtx(ctx: SkillEmbedCtx): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SS_KEY, JSON.stringify(ctx));
}

export function clearSkillCtx(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(SS_KEY);
}

/** Read query params on /new and bootstrap the sessionStorage ctx. */
export function bootstrapSkillCtxFromUrl(): SkillEmbedCtx | null {
  if (typeof window === "undefined") return null;
  const p = new URLSearchParams(window.location.search);
  if (p.get("embed") !== "skill") return null;
  const slug = p.get("skill_slug");
  const docId = Number(p.get("skill_doc_id"));
  const slot = p.get("slot");
  if (!slug || !docId || !slot) return null;
  const trigType = p.get("trigger_type") === "schedule" ? "schedule" : "event";
  const ctx: SkillEmbedCtx = {
    skill_slug: slug,
    skill_doc_id: docId,
    slot,
    instruction: p.get("instruction") ?? "",
    trigger_type: trigType,
    trigger_event: p.get("trigger_event") ?? undefined,
    target_kind: (p.get("target_kind") as "all" | "tools" | "stations" | null) ?? undefined,
    target_ids: p.get("target_ids")?.split(",").filter(Boolean),
  };
  writeSkillCtx(ctx);
  return ctx;
}

/** Banner component — render once at the top of the Builder page. */
export default function SkillEmbedBanner({ pipelineId }: { pipelineId?: number | null }) {
  const [ctx, setCtx] = useState<SkillEmbedCtx | null>(() => readSkillCtx());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Refresh ctx if sessionStorage changes from another tab.
  useEffect(() => {
    const handler = () => setCtx(readSkillCtx());
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  const onCancel = useCallback(() => {
    if (!confirm("離開後不會把這個 pipeline 綁回 Skill — 你之後仍可在 Pipeline Builder 找到它。確定取消？")) return;
    clearSkillCtx();
    window.close();
    // window.close() only works for tabs the page itself opened; if it
    // failed (current tab was opened directly), redirect back to Skill.
    setTimeout(() => {
      if (ctx) window.location.href = `/skills/${encodeURIComponent(ctx.skill_slug)}/edit`;
    }, 200);
  }, [ctx]);

  const onConfirm = useCallback(async () => {
    if (!ctx || !pipelineId) return;
    setBusy(true); setError(null);
    try {
      const res = await fetch(
        `/api/skill-documents/${encodeURIComponent(ctx.skill_slug)}/bind-pipeline`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot: ctx.slot,
            pipeline_id: pipelineId,
            description: ctx.instruction,
            summary: `Built via Pipeline Builder · ${ctx.slot}`,
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      clearSkillCtx();
      // Try closing the tab; fall back to redirect.
      window.close();
      setTimeout(() => {
        window.location.href = `/skills/${encodeURIComponent(ctx.skill_slug)}/edit`;
      }, 300);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }, [ctx, pipelineId]);

  if (!ctx) return null;

  const slotLabel =
    ctx.slot === "confirm" ? "CONFIRM (C1)"
    : ctx.slot.startsWith("step:") ? `CHECKLIST step "${ctx.slot.slice(5)}"`
    : ctx.slot;

  const triggerSummary =
    ctx.trigger_type === "event"
      ? `event=${ctx.trigger_event ?? "(none)"} (input ← event payload)`
      : `schedule · target=${ctx.target_kind ?? "all"}${ctx.target_ids?.length ? ` (${ctx.target_ids.join(", ")})` : ""}`;

  const canBind = pipelineId != null;

  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 50,
      padding: "10px 18px",
      background: "linear-gradient(90deg, #FEF3C7 0%, #FDE68A 100%)",
      borderBottom: "1px solid #F59E0B",
      display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <span style={{ fontSize: 18 }}>📖</span>
      <div style={{ flex: 1, fontSize: 13, color: "#78350F" }}>
        <strong>為 Skill「{ctx.skill_slug}」建立 {slotLabel}</strong>
        <div style={{ fontSize: 11.5, color: "#92400E", marginTop: 2 }}>
          {triggerSummary}
          {ctx.instruction && <> · 📝 「{ctx.instruction}」</>}
        </div>
      </div>
      {!canBind && (
        <span style={{ fontSize: 11.5, color: "#92400E", fontStyle: "italic" }}>
          先按 Save 取得 pipeline id，再點 Done
        </span>
      )}
      <button
        onClick={onCancel}
        disabled={busy}
        style={{
          padding: "6px 14px", fontSize: 12, fontWeight: 500, borderRadius: 5,
          background: "#fff", color: "#78350F", border: "1px solid #D97706",
          cursor: "pointer",
        }}
      >
        Cancel
      </button>
      <button
        onClick={onConfirm}
        disabled={!canBind || busy}
        style={{
          padding: "6px 16px", fontSize: 12, fontWeight: 600, borderRadius: 5,
          background: canBind ? "#16A34A" : "#94A3B8",
          color: "#fff", border: "none",
          cursor: canBind ? "pointer" : "not-allowed",
          opacity: busy ? 0.6 : 1,
        }}
      >
        {busy ? "Binding…" : "Done — bind to Skill ↵"}
      </button>
      {error && (
        <div style={{ fontSize: 11, color: "#B91C1C", flexBasis: "100%" }}>⚠ {error}</div>
      )}
    </div>
  );
}

/** Hardcoded event_type → input attribute list; mirrors V25 backfill.
 *  Used to seed pendingInputs when bypassing the wizard. */
export function seedInputsFromCtx(ctx: SkillEmbedCtx): { name: string; type: string; required: boolean; description?: string }[] {
  if (ctx.trigger_type === "event") {
    const ev = ctx.trigger_event ?? "";
    if (ev === "OOC") {
      return [
        { name: "tool_id", type: "string", required: true, description: "From OOC payload" },
        { name: "lot_id", type: "string", required: true },
        { name: "step", type: "string", required: false },
        { name: "chamber_id", type: "string", required: false },
        { name: "spc_chart", type: "string", required: false },
        { name: "severity", type: "string", required: false },
      ];
    }
    if (ev === "FDC_FAULT" || ev === "FDC_WARNING") {
      return [
        { name: "tool_id", type: "string", required: true },
        { name: "lot_id", type: "string", required: true },
        { name: "step", type: "string", required: false },
        { name: "chamber_id", type: "string", required: false },
        { name: "fault_code", type: "string", required: false },
      ];
    }
    if (ev === "PM_START" || ev === "PM_DONE") {
      return [
        { name: "tool_id", type: "string", required: true },
        { name: "reason", type: "string", required: false },
      ];
    }
    if (ev === "EQUIPMENT_HOLD") {
      return [
        { name: "tool_id", type: "string", required: true },
        { name: "lot_id", type: "string", required: false },
        { name: "step", type: "string", required: false },
      ];
    }
    if (ev === "RECIPE_VERSION_BUMP") {
      return [
        { name: "recipe_id", type: "string", required: true },
        { name: "new_version", type: "number", required: true },
      ];
    }
    if (ev === "ENGINEER_OVERRIDE") {
      return [
        { name: "object_name", type: "string", required: true },
        { name: "object_id", type: "string", required: true },
        { name: "parameter", type: "string", required: true },
        { name: "engineer", type: "string", required: true },
      ];
    }
    // Generic event fallback — at least pass tool_id.
    return [{ name: "tool_id", type: "string", required: true }];
  }
  // schedule trigger — input is the target object the cron iterates over.
  if (ctx.target_kind === "tools" && ctx.target_ids?.length) {
    return [{
      name: "tool_id", type: "string", required: true,
      description: `Iterating over: ${ctx.target_ids.join(", ")}`,
    }];
  }
  if (ctx.target_kind === "stations" && ctx.target_ids?.length) {
    return [{
      name: "station_id", type: "string", required: true,
      description: `Iterating over: ${ctx.target_ids.join(", ")}`,
    }];
  }
  // all
  return [{ name: "tool_id", type: "string", required: true, description: "Iterating over all 10 tools" }];
}
