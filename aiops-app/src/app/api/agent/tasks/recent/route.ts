/** ChatOps rail 最近運作 (2026-07-13) — 本人跨對話近期背景工作。 */
import { NextResponse, type NextRequest } from "next/server";
import { getBearerToken } from "@/lib/auth-proxy";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest) {
  const authCtx = await getBearerToken();
  if (authCtx.source !== "session" || !authCtx.userId) {
    return NextResponse.json({ tasks: [] });
  }
  try {
    const res = await fetch(
      `${SIDECAR_BASE}/internal/agent/tasks/recent?user_id=${authCtx.userId}`,
      { headers: { "X-Service-Token": SIDECAR_TOKEN }, cache: "no-store" },
    );
    return new NextResponse(await res.text(), {
      status: res.status, headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ tasks: [] });
  }
}
