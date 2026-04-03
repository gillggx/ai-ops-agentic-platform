import { NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

/** Fetch event_types from FastAPI backend for the skill trigger dropdown. */
export async function GET() {
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/event-types`, {
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${TOKEN}`,
      },
      cache: "no-store",
    });
    const data = await res.json();
    const items = data.data ?? data;
    return NextResponse.json(Array.isArray(items) ? items : []);
  } catch (err) {
    console.error("[skills/event-types GET]", err);
    return NextResponse.json([]);
  }
}
