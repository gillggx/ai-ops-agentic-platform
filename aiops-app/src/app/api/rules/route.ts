import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/** Phase 9 — proxy for /api/v1/rules (personal rules owned by caller). */

export async function GET() {
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/rules`, {
      headers: await authHeaders(),
      cache: "no-store",
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ ok: false, error: data?.error ?? data }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("[rules GET]", err);
    return NextResponse.json({ ok: false, error: { message: "proxy failed" } }, { status: 502 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  // Java expects camelCase via Jackson SNAKE_CASE setting; we send snake_case.
  const res = await fetch(`${FASTAPI_BASE}/api/v1/rules`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json({ ok: false, error: data?.error ?? data }, { status: res.status });
  }
  return NextResponse.json(data, { status: 201 });
}
