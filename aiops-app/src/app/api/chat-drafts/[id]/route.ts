import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

// Chat 草稿暫存區 (V78) — get one (full pipeline_json) / delete one.
export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${BASE}/api/v1/chat-drafts/${encodeURIComponent(id)}`, {
    headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${BASE}/api/v1/chat-drafts/${encodeURIComponent(id)}`, {
    method: "DELETE", headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
