import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/** Phase 9 — bell icon polls this. Returns {ok, data:{unreadCount, items}}. */

export async function GET(req: NextRequest) {
  const url = new URL(`${FASTAPI_BASE}/api/v1/notifications/inbox`);
  const unread = req.nextUrl.searchParams.get("unreadOnly");
  const limit = req.nextUrl.searchParams.get("limit");
  if (unread) url.searchParams.set("unreadOnly", unread);
  if (limit) url.searchParams.set("limit", limit);
  try {
    const res = await fetch(url.toString(), {
      headers: await authHeaders(),
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[notifications/inbox GET]", err);
    return NextResponse.json({ ok: false, error: { message: "proxy failed" } }, { status: 502 });
  }
}
