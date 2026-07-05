import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/** i18n P3 — persist the user's UI locale (users.locale via Java). */
export async function PUT(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auth/me/locale`, {
    method: "PUT",
    headers: await authHeaders(),
    body,
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
