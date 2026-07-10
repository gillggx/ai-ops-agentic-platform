import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function PUT(req: NextRequest, ctx: { params: Promise<{ name: string }> }) {
  const { name } = await ctx.params;
  const res = await fetch(`${BASE}/api/v1/agent-skills/${encodeURIComponent(decodeURIComponent(name))}`, {
    method: "PUT",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: await req.text(),
  });
  return new Response(await res.text(), {
    status: res.status, headers: { "Content-Type": "application/json" },
  });
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ name: string }> }) {
  const { name } = await ctx.params;
  const res = await fetch(`${BASE}/api/v1/agent-skills/${encodeURIComponent(decodeURIComponent(name))}`, {
    method: "DELETE", headers: await authHeaders(),
  });
  return new Response(await res.text(), {
    status: res.status, headers: { "Content-Type": "application/json" },
  });
}
