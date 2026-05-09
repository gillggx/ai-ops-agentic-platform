import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

// Phase 11 v2 — set/replace the optional CONFIRM (gating) step.
export async function POST(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const body = await req.text();
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/confirm-check`,
    { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body },
  );
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

// Drop the CONFIRM step.
export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/confirm-check`,
    { method: "DELETE", headers },
  );
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
