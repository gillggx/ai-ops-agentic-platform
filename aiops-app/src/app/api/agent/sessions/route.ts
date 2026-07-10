import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

// ChatOps sidebar — list the caller's agent sessions (Java agent_sessions).
const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const limit = req.nextUrl.searchParams.get("limit") ?? "50";
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/agent/sessions?limit=${encodeURIComponent(limit)}`, {
    headers, cache: "no-store",
  });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
