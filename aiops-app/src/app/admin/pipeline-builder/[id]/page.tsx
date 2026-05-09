"use client";

import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import SurfaceTour from "@/components/tour/SurfaceTour";
import { PIPELINE_BUILDER_STEPS } from "@/components/tour/steps/pipeline-builder";
import SkillEmbedBanner from "@/components/pipeline-builder/SkillEmbedBanner";

const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

export default function EditPipelinePage() {
  const params = useParams();
  const idStr = Array.isArray(params.id) ? params.id[0] : params.id;
  const id = idStr ? Number(idStr) : undefined;
  if (!id || Number.isNaN(id)) {
    return <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>無效的 pipeline id</div>;
  }
  return (
    <>
      {/* Phase 11 v4 — banner only renders when sessionStorage has a skill
          embed ctx (set on /new ?embed=skill landing). On /[id] the
          pipeline already has an id, so "Done — bind" can fire. */}
      <SkillEmbedBanner pipelineId={id}/>
      <BuilderLayout mode="edit" pipelineId={id} />
      <SurfaceTour surfaceId="pipeline-builder" steps={PIPELINE_BUILDER_STEPS} />
    </>
  );
}
