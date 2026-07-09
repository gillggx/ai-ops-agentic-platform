import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

// Persist the user's UI theme preference (design v2, 10 themes).
// Body: { theme: "pine" | "oxblood" | ... } → Java PUT /api/v1/auth/me/theme.
export async function PUT(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auth/me/theme`, {
    method: "PUT",
    headers: await authHeaders(),
    body,
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
