"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import SurfaceTour from "@/components/tour/SurfaceTour";
import { PIPELINE_BUILDER_STEPS } from "@/components/tour/steps/pipeline-builder";
import SkillEmbedBanner, { bootstrapSkillCtxFromUrl } from "@/components/pipeline-builder/SkillEmbedBanner";

const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

export default function EditPipelinePage() {
  const params = useParams();
  const idStr = Array.isArray(params.id) ? params.id[0] : params.id;
  const id = idStr ? Number(idStr) : undefined;

  // Phase 11 v6 — refine flow lands directly on /[id]?embed=skill&...
  // Bootstrap sessionStorage ctx so the SkillEmbedBanner renders.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    bootstrapSkillCtxFromUrl();
    setReady(true);
  }, []);

  if (!id || Number.isNaN(id)) {
    return <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>無效的 pipeline id</div>;
  }
  if (!ready) return null;

  return (
    <>
      <SkillEmbedBanner pipelineId={id}/>
      <BuilderLayout mode="edit" pipelineId={id} />
      <SurfaceTour surfaceId="pipeline-builder" steps={PIPELINE_BUILDER_STEPS} />
    </>
  );
}
