/** V85 (2026-07-11) — 對話的背景 Agent Task 清單（reattach 用）。 */
import { NextResponse, type NextRequest } from "next/server";
import { getBearerToken } from "@/lib/auth-proxy";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const authCtx = await getBearerToken();
  if (authCtx.source !== "session") {
    return NextResponse.json({ error: "login required" }, { status: 401 });
  }
  const sid = req.nextUrl.searchParams.get("session_id");
  if (!sid) return NextResponse.json({ error: "session_id required" }, { status: 400 });
  try {
    const res = await fetch(
      `${SIDECAR_BASE}/internal/agent/tasks?chat_session_id=${encodeURIComponent(sid)}`,
      { headers: { "X-Service-Token": SIDECAR_TOKEN, "X-User-Id": String(authCtx.userId ?? 0) },
        cache: "no-store" },
    );
    return new NextResponse(await res.text(), {
      status: res.status, headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
