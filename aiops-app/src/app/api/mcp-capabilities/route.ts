import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

// MCP capability registry catalog (IT_ADMIN). Proxies to Java
// /api/v1/mcp-capabilities — built-in tools + domain skills + external MCPs
// with each capability's public/private + write flag.
export async function GET(_req: NextRequest) {
  const res = await fetch(`${FASTAPI_BASE}/api/v1/mcp-capabilities`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  return NextResponse.json(data.data ?? data);
}
