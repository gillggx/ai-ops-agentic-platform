import { NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
import { INTERNAL_API_TOKEN as TOKEN } from "@/lib/internal-token";

export async function GET() {
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/system/monitor`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
