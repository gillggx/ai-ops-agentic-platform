import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const activeOnly = req.nextUrl.searchParams.get("active_only") ?? "false";
  const withStats = req.nextUrl.searchParams.get("with_stats") ?? "true";
  try {
    const res = await fetch(
      `${FASTAPI_BASE}/api/v1/auto-patrols?active_only=${activeOnly}&with_stats=${withStats}`,
      { headers: await authHeaders(), cache: "no-store" }
    );
    const data = await res.json();
    const list = data.data ?? data;
    return NextResponse.json(Array.isArray(list) ? list : []);
  } catch (err) {
    console.error("[auto-patrols GET]", err);
    return NextResponse.json([], { status: 200 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auto-patrols`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? "建立失敗" },
      { status: res.status }
    );
  }
  return NextResponse.json(data.data ?? data, { status: 201 });
}
