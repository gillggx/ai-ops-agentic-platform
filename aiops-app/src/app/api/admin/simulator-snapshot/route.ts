import { NextResponse } from "next/server";

const ONTOLOGY_BASE = process.env.ONTOLOGY_BASE_URL ?? "http://localhost:8012";

export async function GET() {
  try {
    const r = await fetch(`${ONTOLOGY_BASE}/api/v1/admin/snapshot`, {
      cache: "no-store",
    });
    if (!r.ok) {
      return NextResponse.json(
        { error: `simulator returned ${r.status}` },
        { status: r.status },
      );
    }
    const body = await r.json();
    return NextResponse.json(body);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 503 },
    );
  }
}
