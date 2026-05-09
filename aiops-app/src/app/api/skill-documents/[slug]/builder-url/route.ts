import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

// Phase 11 v4 — get the Pipeline Builder URL (with seeded query params)
// the Skill UI should open in a new tab to author a confirm/step pipeline.
export async function GET(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const slot = req.nextUrl.searchParams.get("slot") ?? "";
  const instruction = req.nextUrl.searchParams.get("instruction") ?? "";
  const headers = await authHeaders();
  const url = `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/builder-url`
    + `?slot=${encodeURIComponent(slot)}&instruction=${encodeURIComponent(instruction)}`;
  const res = await fetch(url, { headers });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
