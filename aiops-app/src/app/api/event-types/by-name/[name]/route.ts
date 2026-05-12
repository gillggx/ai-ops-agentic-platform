import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

// Pipeline Builder wizard reads event_type.attributes (payload schema)
// to pre-populate pipeline.inputs when the skill is wired to an
// event-driven trigger. Returns 404 when the name is unknown so the
// wizard can fall back to its generic heuristics.
export async function GET(_req: NextRequest, ctx: { params: Promise<{ name: string }> }) {
  const { name } = await ctx.params;
  const headers = await authHeaders();
  const url = `${BASE}/api/v1/event-types/by-name/${encodeURIComponent(name)}`;
  const res = await fetch(url, { headers });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
