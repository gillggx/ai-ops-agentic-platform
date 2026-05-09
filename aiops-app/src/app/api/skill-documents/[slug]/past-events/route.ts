import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/past-events`,
    { headers, cache: "no-store" },
  );
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
