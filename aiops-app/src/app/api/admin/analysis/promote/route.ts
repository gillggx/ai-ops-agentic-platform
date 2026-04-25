import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/analysis/promote`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TOKEN}`,
      },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { message: data.message ?? data.detail ?? "Promote failed" },
        { status: res.status }
      );
    }
    return NextResponse.json(data.data ?? data, { status: 201 });
  } catch (err) {
    console.error("[analysis promote]", err);
    return NextResponse.json({ message: "promote failed" }, { status: 500 });
  }
}
