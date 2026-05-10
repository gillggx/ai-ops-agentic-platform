import { redirect } from "next/navigation";

// Phase 11 v6 — Skill Library is the single authoring entry point.
// The free-standing Pipeline Builder list is hidden; users reach the
// Builder only through the Skill embed flow (Skill → Build/Refine →
// /admin/pipeline-builder/new?embed=skill&...).
//
// The original list-page implementation lives in git history; the
// component file is preserved in v6's TO-REMOVE list memory and will
// be physically deleted once the new flow is confirmed.
export default function PipelineBuilderListRedirect() {
  redirect("/skills");
}
