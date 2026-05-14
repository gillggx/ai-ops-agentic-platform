import { NextResponse } from "next/server";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ file: string }> },
) {
  if (!SIDECAR_TOKEN) {
    return NextResponse.json(
      { error: "SIDECAR_SERVICE_TOKEN not configured" },
      { status: 503 },
    );
  }
  const { file } = await ctx.params;
  // Defence: filename must end in .json + no path separators
  if (!file || file.includes("/") || file.includes("..") || !file.endsWith(".json")) {
    return NextResponse.json({ error: "bad filename" }, { status: 400 });
  }
  try {
    const res = await fetch(
      `${SIDECAR_BASE}/internal/agent/build/traces/${encodeURIComponent(file)}`,
      {
        headers: { "X-Service-Token": SIDECAR_TOKEN, Accept: "application/json" },
        cache: "no-store",
      },
    );
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
