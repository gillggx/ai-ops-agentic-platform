/** V85 (2026-07-11) — 跨裝置 rich history（完整訊息串含圖卡，opaque JSON blob）。 */
import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await ctx.params;
  const res = await fetch(
    `${BASE}/api/v1/agent/session/${encodeURIComponent(sessionId)}/rich-history`,
    { headers: await authHeaders(), cache: "no-store" },
  );
  return new Response(await res.text(), {
    status: res.status, headers: { "Content-Type": "application/json" },
  });
}

export async function PUT(req: NextRequest, ctx: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await ctx.params;
  const body = await req.text();
  const res = await fetch(
    `${BASE}/api/v1/agent/session/${encodeURIComponent(sessionId)}/rich-history`,
    { method: "PUT",
      headers: { ...(await authHeaders()), "Content-Type": "application/json" },
      body, cache: "no-store" },
  );
  return new Response(await res.text(), {
    status: res.status, headers: { "Content-Type": "application/json" },
  });
}
