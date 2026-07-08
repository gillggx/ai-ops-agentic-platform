import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

// Chat 草稿暫存區 (V78) — toggle 標記 (pin). Marked drafts never auto-evict.
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await req.text();
  const res = await fetch(`${BASE}/api/v1/chat-drafts/${encodeURIComponent(id)}/mark`, {
    method: "PATCH",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body,
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
