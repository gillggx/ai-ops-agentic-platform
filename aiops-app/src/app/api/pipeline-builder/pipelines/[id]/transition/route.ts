import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "../../../_common";

// Lifecycle moved to PipelineController (Java) at /api/v1/pipelines/{id}/transition,
// alongside create/update/delete. PipelineBuilderController stays read-only.
const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const CRUD_BASE = `${FASTAPI_BASE}/api/v1/pipelines`;

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await req.json();
  const res = await fetch(`${CRUD_BASE}/${id}/transition`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
