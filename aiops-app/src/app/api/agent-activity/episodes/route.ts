import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";
const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";
// GET /api/agent-activity/episodes?limit=30 -> Java list
export async function GET(req: NextRequest) {
  const limit = req.nextUrl.searchParams.get("limit") ?? "30";
  const res = await fetch(`${BASE}/api/v1/agent-activity/episodes?limit=${encodeURIComponent(limit)}`,
    { headers: await authHeaders() });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
