import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";
const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";
export async function GET(req: NextRequest) {
  const days = req.nextUrl.searchParams.get("days") ?? "30";
  const res = await fetch(`${BASE}/api/v1/agent-activity/report?days=${encodeURIComponent(days)}`,
    { headers: await authHeaders() });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
