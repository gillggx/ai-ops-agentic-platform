import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const url = new URL(req.url);
  const test = url.searchParams.get("test");
  const qs = test !== null ? `?test=${encodeURIComponent(test)}` : "";
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/runs${qs}`,
    { headers, cache: "no-store" },
  );
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
