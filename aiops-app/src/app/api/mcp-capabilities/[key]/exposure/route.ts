import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

// Flip a capability's public/private (IT_ADMIN). Body (snake_case wire):
// { kind, is_public }.
export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ key: string }> },
) {
  const { key } = await params;
  const body = await req.text();
  const res = await fetch(
    `${FASTAPI_BASE}/api/v1/mcp-capabilities/${encodeURIComponent(key)}/exposure`,
    { method: "PUT", headers: await authHeaders(), body },
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
