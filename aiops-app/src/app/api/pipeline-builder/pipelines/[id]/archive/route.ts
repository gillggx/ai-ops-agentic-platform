import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "../../../_common";

// Lifecycle (transition / archive / fork / etc.) lives on PipelineController
// at /api/v1/pipelines/{id}/... — NOT under /pipeline-builder which is the
// read-only listing controller. BACKEND_BASE includes the wrong prefix for
// these mutating calls; use the absolute CRUD path instead.
const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const CRUD_BASE = `${FASTAPI_BASE}/api/v1/pipelines`;

export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${CRUD_BASE}/${id}/archive`, {
    method: "POST",
    headers: await authHeaders(),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
