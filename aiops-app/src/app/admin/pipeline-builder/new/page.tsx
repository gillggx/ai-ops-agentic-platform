"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { PipelineInput, PipelineJSON } from "@/lib/pipeline-builder/types";
import type { AutoPatrolTriggerValue } from "@/components/pipeline-builder/AutoPatrolTriggerForm";
import type { AutoCheckTriggerValue } from "@/components/pipeline-builder/AutoCheckTriggerForm";
import type { PickedScope } from "@/components/pipeline-builder/AutoPatrolScopePicker";
import SurfaceTour from "@/components/tour/SurfaceTour";
import { PIPELINE_BUILDER_STEPS } from "@/components/tour/steps/pipeline-builder";
import SkillEmbedBanner, {
  bootstrapSkillCtxFromUrl,
  readSkillCtx,
  seedInputsFromCtx,
} from "@/components/pipeline-builder/SkillEmbedBanner";
import SkillV2EmbedBanner, {
  bootstrapSkillV2CtxFromUrl,
  readSkillV2Ctx,
} from "@/components/skills-v2/SkillV2EmbedBanner";

// React Flow can't SSR
const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

type Kind = "auto_patrol" | "auto_check" | "skill";

/** Payload handed to BuilderLayout. Auto-created on first save.
 *
 *  The 3-step wizard that used to populate this on /new was sunset on
 *  2026-07-05 (skills_v2 編寫 flow is the only authoring entry now), so
 *  this page always passes null — the type stays exported because
 *  BuilderLayout still accepts it from other mounts. */
export type PendingTrigger =
  | { kind: "auto_patrol"; config: AutoPatrolTriggerValue; scope: PickedScope }
  | { kind: "auto_check"; config: AutoCheckTriggerValue }
  | null;

/** Ephemeral pipeline handed over from chat / Lite Canvas. Kept in
 *  sessionStorage across refreshes (TTL below) so F5 re-hydrates the same
 *  canvas instead of dumping the user onto a dead entry point. */
const EPHEMERAL_TTL_MS = 60 * 60 * 1000;

export default function NewPipelinePage() {
  const [kind, setKind] = useState<Kind | null>(null);
  const [pendingInputs, setPendingInputs] = useState<PipelineInput[]>([]);
  const [ephemeralPipeline, setEphemeralPipeline] = useState<PipelineJSON | null>(null);
  const [checkedSession, setCheckedSession] = useState(false);
  const [shouldRedirect, setShouldRedirect] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let hydrated: PipelineJSON | null = null;
    try {
      const raw = sessionStorage.getItem("pb:ephemeral_pipeline");
      if (raw) {
        const payload = JSON.parse(raw) as { pipeline_json?: PipelineJSON; ts?: number };
        const fresh = typeof payload?.ts === "number"
          ? Date.now() - payload.ts < EPHEMERAL_TTL_MS
          : false;
        if (payload?.pipeline_json && fresh) {
          hydrated = payload.pipeline_json;
          setEphemeralPipeline(payload.pipeline_json);
          // Deliberately NOT removed: a refresh must re-hydrate the same
          // canvas. The TTL (or a malformed payload) is what clears it.
        } else {
          sessionStorage.removeItem("pb:ephemeral_pipeline");
        }
      }
    } catch {
      try { sessionStorage.removeItem("pb:ephemeral_pipeline"); } catch { /* ignore */ }
    }

    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      // PbPipelineCard.handleEditInBuilder uses ?from=chat; AIAgentPanel /
      // LiteCanvasOverlay use ?from=agent. Both mean "Glass Box already
      // built it, drop user onto canvas".
      const fromParam = params.get("from");
      const fromAgent = fromParam === "agent" || fromParam === "chat";
      const skillCtx = bootstrapSkillCtxFromUrl();
      const skillV2Ctx = bootstrapSkillV2CtxFromUrl();

      // Heuristic: pipeline_json shape decides the kind. block_alert ⇒ auto_patrol;
      // otherwise skill.
      const inferKind = (pj: PipelineJSON): Kind =>
        pj.nodes.some((n) => n.block_id === "block_alert") ? "auto_patrol" : "skill";

      if (skillCtx) {
        // Skill embed: kind="skill" (no alert; ends in step_check), seed inputs
        // from the trigger event payload or schedule target. seedInputsFromCtx
        // is async — when trigger.event is set it pulls event_types.attributes
        // from Java so the LLM sees the same field names that arrive at runtime.
        setKind("skill");
        seedInputsFromCtx(skillCtx).then((seeds) => {
          const seeded = seeds.map((s) => ({
            name: s.name, type: s.type, required: s.required,
            description: s.description ?? "",
            // Carry the canonical example so Pipeline Builder's Run Full
            // dialog auto-fills each field — user only types when they want
            // to override.
            ...(s.example !== undefined ? { example: s.example } : {}),
          })) as PipelineInput[];
          setPendingInputs(seeded);
        }).catch(() => {
          // seedInputsFromCtx already swallows fetch errors and returns a
          // safe fallback; this catch handles only Promise rejection edge.
        });
      } else if (skillV2Ctx) {
        // Skills v2 embed: bind target is skills_v2.pipeline_id (handled
        // by SkillV2EmbedBanner).
        setKind("skill");
      } else if (fromAgent && hydrated) {
        // Agent already built the pipeline — straight onto the canvas.
        setKind(inferKind(hydrated));
      } else {
        // 2026-07-05 wizard sunset: every other entry (?kind=, bare URL,
        // ?from=catalog, from=chat/agent whose sessionStorage expired) goes
        // to the Skill Library — authoring starts there now.
        setShouldRedirect(true);
      }
    }
    setCheckedSession(true);
  }, []);

  // Redirect after render so router is available.
  useEffect(() => {
    if (shouldRedirect) router.replace("/skills");
  }, [shouldRedirect, router]);

  if (!checkedSession || shouldRedirect || !kind) return null;

  // Hand off to BuilderLayout. Inputs ride on the initial pipeline_json.
  const initialJson: PipelineJSON = {
    version: "1.0",
    name: "新 Pipeline",
    metadata: {},
    nodes: ephemeralPipeline?.nodes ?? [],
    edges: ephemeralPipeline?.edges ?? [],
    inputs: pendingInputs.length > 0
      ? pendingInputs
      : (ephemeralPipeline?.inputs ?? []),
  };
  // Phase 11 v4: pipelineId is null on /new (gets one after first save +
  // BuilderLayout navigates to /[id]). Banner shows "press Save first" hint.
  // Phase 11 v6 — when launched via Skill embed, suppress the onboarding
  // tour (its fixed-position mask covers the canvas).
  const inSkillEmbed = readSkillCtx() != null;
  const inSkillV2Embed = readSkillV2Ctx() != null;
  return (
    <>
      {inSkillV2Embed
        ? <SkillV2EmbedBanner pipelineId={null}/>
        : <SkillEmbedBanner pipelineId={null}/>}
      <BuilderLayout
        mode="new"
        initialKind={kind}
        initialPipelineJson={initialJson}
        initialPendingTrigger={null}
        initialPrompt={readSkillCtx()?.instruction}
      />
      {!inSkillEmbed && <SurfaceTour surfaceId="pipeline-builder" steps={PIPELINE_BUILDER_STEPS} />}
    </>
  );
}
