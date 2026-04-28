import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../../_common";

// Same split as ../route.ts: read = PipelineBuilderController (rich DTO),
// write = PipelineController (CRUD).
const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const CRUD_BASE = `${FASTAPI_BASE}/api/v1/pipelines`;

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${BACKEND_BASE}/pipelines/${id}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function PUT(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await req.json();
  const res = await fetch(`${CRUD_BASE}/${id}`, {
    method: "PUT",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${CRUD_BASE}/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (res.status === 204) return new NextResponse(null, { status: 204 });
  const data = await res.json().catch(() => null);
  return NextResponse.json(data, { status: res.status });
}
