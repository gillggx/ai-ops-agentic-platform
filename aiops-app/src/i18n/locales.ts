/** i18n 共用常數 — client/server 都會 import，不可放 next/headers 相依。 */
export const SUPPORTED_LOCALES = ["zh-TW", "zh-CN", "en", "ja"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: AppLocale = "zh-TW";

/** 切換器顯示用 — 各語系用「自己的」寫法（endonym），業界慣例不翻譯。 */
export const LOCALE_LABELS: Record<AppLocale, string> = {
  "zh-TW": "繁體中文",
  "zh-CN": "简体中文",
  "en": "English",
  "ja": "日本語",
};
