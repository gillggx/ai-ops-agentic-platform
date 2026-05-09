import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

/**
 * POST /api/skill-documents/[slug]/run
 *  body: { trigger_payload?: Record<string, any>, is_test?: boolean }
 * Forwards to Java /api/v1/skill-documents/[slug]/run which dispatches
 * SkillRunner. SSE stream relays per-step status back.
 */
export async function POST(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const body = await req.text();
  const headers = await authHeaders();
  const upstream = await fetch(
    `${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}/run`,
    {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json", Accept: "text/event-stream" },
      body,
      // @ts-expect-error: Node.js fetch duplex
      duplex: "half",
    },
  );
  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || `upstream ${upstream.status}`, { status: upstream.status });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
