import { NextResponse } from "next/server";
import { authHeaders as authHeadersFromSession } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET() {
  const url = `${FASTAPI_BASE}/api/v1/block-docs`;
  const res = await fetch(url, {
    headers: await authHeadersFromSession(),
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
