import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

/** Flip stage draft → stable. Idempotent — re-activate bumps minor version. */
export async function POST(_req: NextRequest, ctx: { params: Promise<{ slug: string; kind: string }> }) {
  const { slug, kind } = await ctx.params;
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v1/skill-studio/${encodeURIComponent(slug)}/stages/${encodeURIComponent(kind)}/activate`,
    {
      method: "POST",
      headers,
      cache: "no-store",
    },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
