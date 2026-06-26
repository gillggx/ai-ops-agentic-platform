import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

// GET /api/handoffs/stream -> Java SSE /api/v1/handoffs/stream (auto-popup channel)
export async function GET(_req: NextRequest) {
  const upstream = await fetch(`${BASE}/api/v1/handoffs/stream`, {
    headers: { ...(await authHeaders()), Accept: "text/event-stream" },
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || `upstream ${upstream.status}`, { status: upstream.status });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
