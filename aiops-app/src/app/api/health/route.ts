import { NextResponse } from "next/server";

// Minimal liveness probe consumed by SystemMonitorAliasController +
// docker compose / K8s readiness checks. Stays cheap on purpose — no DB
// or upstream dependency calls. If aiops-app is reachable here, the
// Next.js server is up.
export async function GET() {
  return NextResponse.json({ status: "UP", service: "aiops-app" });
}
