import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.AGENT_BUILD_BASE_URL
  ?? process.env.FASTAPI_BASE_URL
  ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/agent/build/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const data = await res.json().catch(() => null);
  return NextResponse.json(data, { status: res.status });
}
