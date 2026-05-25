import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.AGENT_BUILD_BASE_URL
  ?? process.env.FASTAPI_BASE_URL
  ?? "http://localhost:8000";
import { INTERNAL_API_TOKEN as TOKEN } from "@/lib/internal-token";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/agent/build/${encodeURIComponent(id)}`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
