import { NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

export async function GET() {
  const res = await fetch(`${BACKEND_BASE}/auto-check-rules`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
