import type { Metadata, Viewport } from "next";
import "./globals.css";
import "@/styles/tour.css";
import "@/styles/themes.css";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { AppShell } from "@/components/shell/AppShell";
import SessionProviderWrapper from "@/components/shell/SessionProviderWrapper";
import { TourRoot } from "@/components/tour/TourRoot";

export const metadata: Metadata = {
  title: "AIOps",
  description: "AIOps Application",
};

// 手機 (2026-07-11)：viewport-fit=cover 讓 env(safe-area-inset-*) 生效
// （底部 tab bar 避開 iPhone home indicator）。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // i18n P0 — locale 由 NEXT_LOCALE cookie 決定（src/i18n/request.ts），
  // 無 URL routing。Provider 讓所有 client component 可用 useTranslations。
  const locale = await getLocale();
  return (
    <html lang={locale} suppressHydrationWarning>
      <body>
        {/* Theme pre-paint: apply the cached theme before first paint so a
            non-default theme doesn't flash. DB (ui_theme on the user) is the
            source of truth; localStorage is only a per-browser paint cache
            that AppShell refreshes after loading the profile. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('ui_theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}",
          }}
        />
        <NextIntlClientProvider>
          <SessionProviderWrapper>
            <TourRoot>
              <AppShell>{children}</AppShell>
            </TourRoot>
          </SessionProviderWrapper>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
