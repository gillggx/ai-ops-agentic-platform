import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

// Paths accessible without a session.
const PUBLIC_PATHS = [
  "/login",
  "/api/auth",          // NextAuth callbacks
  "/_next",
  "/favicon",
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();

  // NextAuth v5: `auth()` inside middleware returns current session or null.
  const session = await auth();
  if (!session) {
    // Backwards-compat: if the platform is still in "shared-token" mode
    // (no user sessions yet), skip the redirect. Gated by an env flag so
    // EC2 can flip to strict-auth mode when ready.
    if (process.env.AIOPS_AUTH_REQUIRED !== "1") {
      return NextResponse.next();
    }
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match everything except Next internals and static files
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
