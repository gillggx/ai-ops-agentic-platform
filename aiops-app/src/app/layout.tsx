import type { Metadata } from "next";
import "./globals.css";
import "@/styles/tour.css";
import { AppShell } from "@/components/shell/AppShell";
import SessionProviderWrapper from "@/components/shell/SessionProviderWrapper";
import { TourRoot } from "@/components/tour/TourRoot";

export const metadata: Metadata = {
  title: "AIOps",
  description: "AIOps Application",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-TW">
      <body>
        <SessionProviderWrapper>
          <TourRoot>
            <AppShell>{children}</AppShell>
          </TourRoot>
        </SessionProviderWrapper>
      </body>
    </html>
  );
}
