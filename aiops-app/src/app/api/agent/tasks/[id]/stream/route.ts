/** V85 (2026-07-11) — reattach 背景 Agent Task 的事件流（回放+即時）。 */
import { NextResponse, type NextRequest } from "next/server";
import { getBearerToken } from "@/lib/auth-proxy";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const authCtx = await getBearerToken();
  if (authCtx.source !== "session") {
    return NextResponse.json({ error: "login required" }, { status: 401 });
  }
  const { id } = await ctx.params;
  try {
    const upstream = await fetch(
      `${SIDECAR_BASE}/internal/agent/tasks/${encodeURIComponent(id)}/stream`,
      { headers: { "X-Service-Token": SIDECAR_TOKEN, "X-User-Id": String(authCtx.userId ?? 0) },
        cache: "no-store" },
    );
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
