import { NextRequest } from "next/server";

// Phase 8-A A-2: upstream is one-step SSE (Java + sidecar both return
// text/event-stream directly on POST). We pipe the stream back to the client
// instead of buffering + parsing — matches EventSource / fetch-reader shapes
// the Frontend's AgentBuilderPanel expects.
//
// AGENT_BUILD_BASE_URL env var is still respected for local dev (point at
// :8001 if testing against the legacy two-step Python backend — but that
// backend no longer returns SSE on POST so the Frontend would break anyway).
// Default: go through Java at FASTAPI_BASE_URL = :8002.
const FASTAPI_BASE = process.env.AGENT_BUILD_BASE_URL
  ?? process.env.FASTAPI_BASE_URL
  ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export const dynamic = "force-dynamic";  // never cache; SSE

export async function POST(req: NextRequest) {
  const body = await req.text();
  const upstream = await fetch(`${FASTAPI_BASE}/api/v1/agent/build`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      Authorization: `Bearer ${TOKEN}`,
    },
    body,
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || `upstream ${upstream.status}`, {
      status: upstream.status,
    });
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
