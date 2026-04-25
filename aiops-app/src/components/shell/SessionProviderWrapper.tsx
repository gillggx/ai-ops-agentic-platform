"use client";

import { SessionProvider } from "next-auth/react";

export default function SessionProviderWrapper({ children }: { children: React.ReactNode }) {
  // NextAuth's client session provider — enables useSession() anywhere below.
  return <SessionProvider>{children}</SessionProvider>;
}
