import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const headers = await authHeaders({ "Content-Type": "application/json" });
  const res = await fetch(`${FASTAPI_BASE}/api/v1/alarms/${id}/ack`, {
    method: "POST",
    headers,
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json({ error: data?.message ?? data?.error ?? "Failed" }, { status: res.status });
  }
  return NextResponse.json(data?.data ?? data ?? {});
}
