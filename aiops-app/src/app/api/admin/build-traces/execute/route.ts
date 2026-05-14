// POST a pipeline_json (typically from a saved trace) to the sidecar's
// /internal/pipeline/execute and return per-node results. Lets the
// admin viewer "re-run" a trace's pipeline on demand to see fresh
// runtime data even if the original build's dry-run was skipped.

import { NextResponse, type NextRequest } from "next/server";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  if (!SIDECAR_TOKEN) {
    return NextResponse.json(
      { error: "SIDECAR_SERVICE_TOKEN not configured" },
      { status: 503 },
    );
  }
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  const pipeline = (body as { pipeline_json?: unknown })?.pipeline_json;
  if (!pipeline || typeof pipeline !== "object") {
    return NextResponse.json({ error: "pipeline_json required" }, { status: 400 });
  }
  try {
    const res = await fetch(`${SIDECAR_BASE}/internal/pipeline/execute`, {
      method: "POST",
      headers: {
        "X-Service-Token": SIDECAR_TOKEN,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        pipeline_json: pipeline,
        inputs: {},
        triggered_by: "admin-trace-rerun",
      }),
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
