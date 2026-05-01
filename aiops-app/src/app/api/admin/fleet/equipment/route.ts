import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams.toString();
  const url = `${FASTAPI_BASE}/api/v1/fleet/equipment${params ? `?${params}` : ""}`;
  const res = await fetch(url, { headers: await authHeaders() });
  const data = await res.json();
  if (!res.ok) return NextResponse.json({ error: data.message ?? "Failed" }, { status: res.status });
  return NextResponse.json(data.data ?? data);
}
