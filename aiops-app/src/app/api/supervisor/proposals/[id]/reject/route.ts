import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  // Forward the JSON body ({ reason }) — the UI requires a non-empty reason.
  // Java currently ignores it (reject() takes only the path id + principal);
  // forwarding keeps the wire ready for when the reason column lands.
  const body = await req.text();
  const res = await fetch(`${BASE}/api/v1/supervisor/proposals/${encodeURIComponent(id)}/reject`, {
    method: "POST", headers: await authHeaders(), body: body || undefined,
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
