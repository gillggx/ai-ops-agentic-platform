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

import { useCallback, useEffect, useRef, useState } from "react";

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
  /** Phase 11 v6 — set when refining an existing slot's pipeline; banner
   *  renders as "Refining" and the Done callback updates same row. */
  existing_pipeline_id?: number;
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
  const existingPid = Number(p.get("existing_pipeline_id"));
  const ctx: SkillEmbedCtx = {
    skill_slug: slug,
    skill_doc_id: docId,
    slot,
    instruction: p.get("instruction") ?? "",
    trigger_type: trigType,
    trigger_event: p.get("trigger_event") ?? undefined,
    target_kind: (p.get("target_kind") as "all" | "tools" | "stations" | null) ?? undefined,
    target_ids: p.get("target_ids")?.split(",").filter(Boolean),
    existing_pipeline_id: Number.isFinite(existingPid) && existingPid > 0 ? existingPid : undefined,
  };
  writeSkillCtx(ctx);
  return ctx;
}

/** Banner component — render once at the top of the Builder page. */
export default function SkillEmbedBanner({ pipelineId }: { pipelineId?: number | null }) {
  const [ctx, setCtx] = useState<SkillEmbedCtx | null>(() => readSkillCtx());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Phase 11 v18 — silent auto-bind: when in skill embed mode, every time
  // the Builder's own Save produces a fresh pipelineId, POST it to the
  // skill so user doesn't have to remember the green Done button. Tracks
  // last-bound id to avoid spamming bind on every parent re-render.
  // User reported: 「按 save 後回來看還是沒記錄到」 → root cause was Save
  // ≠ Done in this UI; auto-bind eliminates that distinction.
  const lastAutoBoundRef = useRef<number | null>(null);
  const [autoBoundAt, setAutoBoundAt] = useState<number | null>(null);

  // Refresh ctx if sessionStorage changes from another tab.
  useEffect(() => {
    const handler = () => setCtx(readSkillCtx());
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  // Auto-bind effect — runs whenever ctx + pipelineId are both set and
  // the pipelineId hasn't been bound yet this session. Silent (no UI flash);
  // the small「✓ auto-bound」chip is the only feedback so user knows it's safe to leave.
  useEffect(() => {
    if (!ctx || !pipelineId) return;
    if (lastAutoBoundRef.current === pipelineId) return;
    let cancelled = false;
    (async () => {
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
        if (!res.ok) {
          // Don't break user's session; just log + leave Done button as fallback.
          console.warn("auto-bind failed:", res.status);
          return;
        }
        if (cancelled) return;
        lastAutoBoundRef.current = pipelineId;
        setAutoBoundAt(Date.now());
      } catch (e) {
        console.warn("auto-bind error:", e);
      }
    })();
    return () => { cancelled = true; };
  }, [ctx, pipelineId]);

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

  // Phase 11 v6 — refine vs build mode (banner copy + colour cues).
  const isRefine = ctx.existing_pipeline_id != null;
  const verbZh = isRefine ? "調整" : "建立";
  const verbEn = isRefine ? "Refining" : "Building";

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
      <span style={{ fontSize: 18 }}>{isRefine ? "🛠" : "📖"}</span>
      <div style={{ flex: 1, fontSize: 13, color: "#78350F" }}>
        <strong>{verbEn} {slotLabel} for Skill「{ctx.skill_slug}」</strong>
        {isRefine && (
          <span style={{ marginLeft: 8, fontSize: 11, color: "#92400E" }}>
            · pipeline #{ctx.existing_pipeline_id} (will update in place)
          </span>
        )}
        <div style={{ fontSize: 11.5, color: "#92400E", marginTop: 2 }}>
          {triggerSummary}
          {ctx.instruction && <> · 📝 「{ctx.instruction}」</>}
        </div>
      </div>
      <a
        href={`/skills/${encodeURIComponent(ctx.skill_slug)}/edit`}
        style={{
          padding: "6px 12px", fontSize: 11.5, fontWeight: 500,
          color: "#78350F", textDecoration: "none",
          background: "transparent", border: "1px dashed #D97706", borderRadius: 5,
        }}>
        ← back to Skill
      </a>
      {!canBind && (
        <span style={{ fontSize: 11.5, color: "#92400E", fontStyle: "italic" }}>
          先按 Save 取得 pipeline id，再點 Done
        </span>
      )}
      {/* Phase 11 v18 — auto-bind status. autoBoundAt set by the silent
          bind effect when Save successfully writes pipeline_id back to
          skill. User can safely close the tab once they see this. */}
      {autoBoundAt && (
        <span title={`auto-bound at ${new Date(autoBoundAt).toLocaleTimeString()}`}
          style={{
            fontSize: 11.5, color: "#15803D",
            padding: "3px 8px", borderRadius: 4,
            background: "#DCFCE7", border: "1px solid #86EFAC",
            display: "inline-flex", alignItems: "center", gap: 4,
          }}>
          ✓ 已自動綁回 Skill
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
        {busy ? "Binding…" : (isRefine ? `Done — update Skill ${verbZh}` : "Done — bind to Skill ↵")}
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
