/** Activation gate: POST = activate (draft→active), DELETE = deactivate (active→draft). */
import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function POST(_req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v2/skills/${encodeURIComponent(slug)}/activate`,
    { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: "{}", cache: "no-store" },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v2/skills/${encodeURIComponent(slug)}/deactivate`,
    { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: "{}", cache: "no-store" },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
