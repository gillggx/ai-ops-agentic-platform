import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

/** Full-data CSV export — streams the Java passthrough response body
 *  straight to the browser (no buffering; exports can be tens of MB). */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${BACKEND_BASE}/export-csv`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    return NextResponse.json(
      { error: text.slice(0, 400) || `HTTP ${res.status}` },
      { status: res.status },
    );
  }
  return new NextResponse(res.body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition":
        res.headers.get("Content-Disposition") ?? 'attachment; filename="export.csv"',
    },
  });
}
