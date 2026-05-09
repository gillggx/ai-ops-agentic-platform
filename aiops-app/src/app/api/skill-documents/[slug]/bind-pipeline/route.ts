import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

// Phase 11 v4 — Pipeline Builder embed mode calls this on Confirm to wire
// the resulting pipeline_id back into the parent Skill's slot.
export async function POST(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const body = await req.text();
  const headers = await authHeaders();
  const res = await fetch(
    `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/bind-pipeline`,
    { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
