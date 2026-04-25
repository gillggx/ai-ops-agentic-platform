import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const res = await fetch(
      `${FASTAPI_BASE}/api/v1/experience-memory/${id}/reject`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${TOKEN}`,
        },
      }
    );
    const data = await res.json();
    return NextResponse.json(data.data ?? data, { status: res.status });
  } catch (err) {
    console.error("[memories reject]", err);
    return NextResponse.json({ error: "reject failed" }, { status: 500 });
  }
}
