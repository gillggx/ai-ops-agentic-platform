import type { Metadata } from "next";
import "./globals.css";
import "@/styles/tour.css";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { AppShell } from "@/components/shell/AppShell";
import SessionProviderWrapper from "@/components/shell/SessionProviderWrapper";
import { TourRoot } from "@/components/tour/TourRoot";

export const metadata: Metadata = {
  title: "AIOps",
  description: "AIOps Application",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // i18n P0 — locale 由 NEXT_LOCALE cookie 決定（src/i18n/request.ts），
  // 無 URL routing。Provider 讓所有 client component 可用 useTranslations。
  const locale = await getLocale();
  return (
    <html lang={locale}>
      <body>
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
