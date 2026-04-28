import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

// Java split — list/get live on PipelineBuilderController @ /api/v1/pipeline-builder/pipelines
// (rich JOIN + dto for the Pipelines list page), but create/update/delete are on
// PipelineController @ /api/v1/pipelines. The Next.js proxy bridges that asymmetry.
const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const CRUD_BASE = `${FASTAPI_BASE}/api/v1/pipelines`;

export async function GET(req: NextRequest) {
  const status = req.nextUrl.searchParams.get("status");
  const url = `${BACKEND_BASE}/pipelines${status ? `?status=${encodeURIComponent(status)}` : ""}`;
  const res = await fetch(url, { headers: await authHeaders(), cache: "no-store" });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(CRUD_BASE, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
