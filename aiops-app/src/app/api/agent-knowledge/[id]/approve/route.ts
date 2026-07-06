import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

/** POST /api/agent-knowledge/{id}/approve → Java
 *  /api/v1/agent-knowledge/{id}/approve — promotes an ON_DUTY draft
 *  (status draft → active). PE/IT_ADMIN only; Java enforces the role. */
export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${BASE}/api/v1/agent-knowledge/${encodeURIComponent(id)}/approve`, {
    method: "POST", headers: await authHeaders(),
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
