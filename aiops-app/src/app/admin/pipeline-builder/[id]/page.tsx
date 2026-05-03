"use client";

import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import SurfaceTour from "@/components/tour/SurfaceTour";
import { PIPELINE_BUILDER_STEPS } from "@/components/tour/steps/pipeline-builder";

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
      <BuilderLayout mode="edit" pipelineId={id} />
      <SurfaceTour surfaceId="pipeline-builder" steps={PIPELINE_BUILDER_STEPS} />
    </>
  );
}
