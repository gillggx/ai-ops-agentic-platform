import { NextResponse } from "next/server";

// Reads sidecar's BUILDER_TRACE_DIR via /internal/agent/build/traces.
// Sidecar binds 127.0.0.1:8050 only — frontend (Next.js server) is on the
// same EC2 host so localhost works.
const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!SIDECAR_TOKEN) {
    return NextResponse.json(
      { error: "SIDECAR_SERVICE_TOKEN not configured" },
      { status: 503 },
    );
  }
  try {
    const res = await fetch(`${SIDECAR_BASE}/internal/agent/build/traces`, {
      headers: { "X-Service-Token": SIDECAR_TOKEN, Accept: "application/json" },
      cache: "no-store",
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
