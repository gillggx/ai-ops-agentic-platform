import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

// List users — /api/admin/users-manage  →  Java /api/v1/admin/users
// (proxy path differs from Java path to avoid colliding with the existing
// /api/admin/users legacy route; UI always uses /users-manage going forward.)
export async function GET(_req: NextRequest) {
  const res = await fetch(`${FASTAPI_BASE}/api/v1/admin/users`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  return NextResponse.json(data.data ?? data);
}

// Create local user
export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/admin/users`, {
    method: "POST",
    headers: await authHeaders(),
    body,
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
