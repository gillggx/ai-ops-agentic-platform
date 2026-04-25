import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const limit = req.nextUrl.searchParams.get("limit") ?? "100";
  const since = req.nextUrl.searchParams.get("since");
  const qs = new URLSearchParams({ limit });
  if (since) qs.set("since", since);
  const res = await fetch(
    `${FASTAPI_BASE}/api/v1/auto-patrols/${id}/executions?${qs}`,
    { headers: await authHeaders(), cache: "no-store" },
  );
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json({ error: data.message ?? "查詢失敗" }, { status: res.status });
  }
  return NextResponse.json(data.data ?? data);
}
