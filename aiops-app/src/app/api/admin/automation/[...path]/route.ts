/**
 * Automation Proxy — forward requests to FastAPI AIOps backend.
 * Handles streaming SSE responses (try-run-stream) transparently.
 */
import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "dev-token";

type Context = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: Context): Promise<Response> {
  const { path } = await ctx.params;
  const upstreamPath = `/api/v1/${path.join("/")}`;
  const url = new URL(upstreamPath, FASTAPI_BASE);

  // Forward query params
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${INTERNAL_TOKEN}`,
  };

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "DELETE") {
    try { body = JSON.stringify(await req.json()); } catch { body = undefined; }
  }

  const upstream = await fetch(url.toString(), {
    method: req.method,
    headers,
    body,
    // Required for SSE streaming — do not buffer
    // @ts-expect-error: Node.js fetch duplex option
    duplex: "half",
  });

  const contentType = upstream.headers.get("content-type") ?? "";

  // ── SSE streaming: pass through body directly ─────────────────────────────
  if (contentType.includes("text/event-stream")) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Transfer-Encoding": "chunked",
      },
    });
  }

  // ── Regular JSON response ─────────────────────────────────────────────────
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}

export const GET    = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const POST   = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const PATCH  = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const DELETE = (req: NextRequest, ctx: Context) => proxy(req, ctx);
