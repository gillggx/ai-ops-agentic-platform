import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

// SPEC_patrol_pipeline_wiring §1.1 — event_types is now Java-owned (was
// localStorage). Java path keeps name/description/source/isActive/attributes/
// diagnosisSkillIds in pg, which is what the patrol wizard input-mapping
// step needs to read attribute schemas off.

export async function GET() {
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/event-types`, {
      headers: await authHeaders(),
      cache: "no-store",
    });
    const body = await res.json();
    const list = body.data ?? body ?? [];
    return NextResponse.json(Array.isArray(list) ? list : []);
  } catch (err) {
    console.error("[event-types GET]", err);
    return NextResponse.json([], { status: 200 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  // body shape: { name, description, source?, isActive?, attributes? }
  // attributes is a JSON-encoded string [{name,type,required,description,enum?}, ...]
  const res = await fetch(`${FASTAPI_BASE}/api/v1/event-types`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? data.error?.message ?? "建立失敗" },
      { status: res.status },
    );
  }
  return NextResponse.json(data.data ?? data, { status: 201 });
}
