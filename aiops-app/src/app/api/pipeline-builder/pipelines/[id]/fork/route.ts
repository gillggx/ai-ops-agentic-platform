import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "../../../_common";

// Phase 3: fork moved to PipelineController under /api/v1/pipelines.
const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const CRUD_BASE = `${FASTAPI_BASE}/api/v1/pipelines`;

export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${CRUD_BASE}/${id}/fork`, {
    method: "POST",
    headers: await authHeaders(),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
