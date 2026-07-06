import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  // Forward the JSON body ({ reason }) — the UI requires a non-empty reason.
  // Java (W2) parses it into the reject_reason column; Content-Type must be
  // set for Spring @RequestBody binding. Empty body stays legal (old flow).
  const body = await req.text();
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/supervisor/proposals/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: body ? { ...headers, "Content-Type": "application/json" } : headers,
    body: body || undefined,
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
