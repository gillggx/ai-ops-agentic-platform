/**
 * Per-stage proxy. PUT saves prose/trigger/pipeline; the request body is
 * forwarded 1:1 (no field rewriting — snake_case wire per Jackson).
 */

import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

export async function PUT(req: NextRequest, ctx: { params: Promise<{ slug: string; kind: string }> }) {
  const { slug, kind } = await ctx.params;
  const headers = await authHeaders();
  const body = await req.text();
  const res = await fetch(
    `${BASE}/api/v1/skill-studio/${encodeURIComponent(slug)}/stages/${encodeURIComponent(kind)}`,
    {
      method: "PUT",
      headers: { ...headers, "Content-Type": "application/json" },
      body,
      cache: "no-store",
    },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
