"use client";

/**
 * Sticky banner shown in Pipeline Builder when launched from a Skills v2
 * Editor's "重新編譯 ↻" button. Mirrors the legacy SkillEmbedBanner
 * (Phase 11 v4) shape but talks to /api/v2/skills/[slug]/bind-pipeline.
 *
 * Bind happens automatically: every time the Builder produces a fresh
 * pipelineId (after Save), the banner POSTs the id to skills_v2 so the
 * Editor reflects the new pipeline + has_alarm immediately on return.
 * The user doesn't need to remember a green Done button — same lesson
 * the legacy banner learned in v18 ("Save ≠ Done, auto-bind eliminates
 * that confusion").
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

const SS_KEY = "pb:skill_v2_embed_ctx";

export interface SkillV2EmbedCtx {
  skill_slug: string;
  name: string;
  nl: string;
  /**
   * compile  – first-time build from NL (Agent auto-fires + auto-confirms)
   * rebuild  – re-run Agent over an already-bound pipeline (same auto-fire)
   * edit     – open existing pipeline for manual canvas edits; Agent does NOT
   *            auto-fire. User can still type into Agent panel manually.
   */
  mode?: "compile" | "rebuild" | "edit";
}

export function readSkillV2Ctx(): SkillV2EmbedCtx | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(SS_KEY);
    return raw ? (JSON.parse(raw) as SkillV2EmbedCtx) : null;
  } catch {
    return null;
  }
}

export function writeSkillV2Ctx(ctx: SkillV2EmbedCtx): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SS_KEY, JSON.stringify(ctx));
}

export function clearSkillV2Ctx(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(SS_KEY);
}

/**
 * Parse {@code ?embed=skill-v2&slug=X} from the URL into ctx, persist
 * to sessionStorage, and return it. Called from PB pages on mount.
 */
export function bootstrapSkillV2CtxFromUrl(): SkillV2EmbedCtx | null {
  if (typeof window === "undefined") return null;
  const p = new URLSearchParams(window.location.search);
  if (p.get("embed") !== "skill-v2") return null;
  const slug = p.get("slug");
  if (!slug) return null;
  // Existing ctx wins (it carries the NL fetched on the click).
  const existing = readSkillV2Ctx();
  if (existing && existing.skill_slug === slug) return existing;
  const modeRaw = p.get("mode");
  const mode: SkillV2EmbedCtx["mode"] =
    modeRaw === "edit" || modeRaw === "rebuild" || modeRaw === "compile" ? modeRaw : "compile";
  const ctx: SkillV2EmbedCtx = {
    skill_slug: slug,
    name: p.get("name") ?? slug,
    nl: p.get("nl") ?? "",
    mode,
  };
  writeSkillV2Ctx(ctx);
  return ctx;
}

export default function SkillV2EmbedBanner({ pipelineId }: { pipelineId?: number | null }) {
  const [ctx, setCtx] = useState<SkillV2EmbedCtx | null>(() => readSkillV2Ctx());
  const [autoBoundAt, setAutoBoundAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastAutoBoundRef = useRef<number | null>(null);

  useEffect(() => {
    const handler = () => setCtx(readSkillV2Ctx());
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  useEffect(() => {
    if (!ctx || !pipelineId) return;
    if (lastAutoBoundRef.current === pipelineId) return;
    lastAutoBoundRef.current = pipelineId;
    void (async () => {
      try {
        const res = await fetch(`/api/skills-v2/${encodeURIComponent(ctx.skill_slug)}/bind-pipeline`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pipeline_id: pipelineId }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setAutoBoundAt(Date.now());
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [ctx, pipelineId]);

  if (!ctx) return null;

  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 30,
      background: "#fbf2e0", borderBottom: "1px solid #ecdcb6",
      padding: "9px 18px",
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
      font: "500 12.5px 'IBM Plex Sans', system-ui, sans-serif",
      color: "#8a5500",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <span style={{
          font: "600 10.5px 'IBM Plex Mono', ui-monospace, monospace",
          letterSpacing: ".12em", textTransform: "uppercase",
          background: "#fff", padding: "3px 7px", borderRadius: 5,
        }}>SKILL · v2</span>
        <span style={{ fontWeight: 600, color: "#1a1c1f" }}>{ctx.name}</span>
        <span style={{ color: "#9aa0a8", fontSize: 11 }}>
          {pipelineId
            ? (autoBoundAt
                ? "已自動綁回 Skill ✓"
                : "正在綁回 Skill…")
            : "存 pipeline 後會自動綁回 Skill"}
        </span>
        {error && <span style={{ color: "#b42318", fontSize: 11 }}>bind error: {error}</span>}
      </div>
      <Link href={`/skills/${encodeURIComponent(ctx.skill_slug)}`} style={{
        color: "#8a5500", textDecoration: "none",
        font: "600 12px 'IBM Plex Sans', system-ui, sans-serif",
        background: "#fff", border: "1px solid #ecdcb6",
        padding: "5px 11px", borderRadius: 7,
      }}>← back to Skill</Link>
    </div>
  );
}
