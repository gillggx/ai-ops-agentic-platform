import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

/** Compile NL prose → rules. Phase 2 returns canned stub per kind. */
export async function POST(req: NextRequest, ctx: { params: Promise<{ slug: string; kind: string }> }) {
  const { slug, kind } = await ctx.params;
  const headers = await authHeaders();
  const body = await req.text();
  const res = await fetch(
    `${BASE}/api/v1/skill-studio/${encodeURIComponent(slug)}/stages/${encodeURIComponent(kind)}/compile`,
    {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: body || "{}",
      cache: "no-store",
    },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
