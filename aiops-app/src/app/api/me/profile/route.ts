import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(_req: NextRequest) {
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auth/me`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data.data ?? data, { status: res.status });
}

export async function PUT(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auth/me`, {
    method: "PUT",
    headers: await authHeaders(),
    body,
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
