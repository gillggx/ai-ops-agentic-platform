import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "../../../_common";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const CRUD_BASE = `${FASTAPI_BASE}/api/v1/pipelines`;

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const limit = req.nextUrl.searchParams.get("limit") ?? "20";
  const res = await fetch(`${CRUD_BASE}/${id}/runs?limit=${encodeURIComponent(limit)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
