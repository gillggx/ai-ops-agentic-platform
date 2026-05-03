"use client";

/**
 * useUserChartTheme — read/write a user's chart theme preference.
 *
 * Storage: server-side, in user_preferences.preferences (JSON string).
 * Hook returns { theme, saveAsDefault, loading, dirty } with the loaded
 * theme as the initial value, or DEFAULT_THEME if user hasn't saved one.
 *
 * Module-level cache so multiple chart cards on the same page only fetch
 * once. Cache invalidated when saveAsDefault succeeds.
 */

import { useCallback, useEffect, useState } from "react";
import { DEFAULT_THEME, type ChartCardTheme } from "@/components/pipeline-builder/charts";

const PREF_KEY = "chart_theme";

interface PreferencesEnvelope {
  id?: number | null;
  userId?: number | null;
  preferences?: string | null;  // JSON string
}

let _cache: { theme: ChartCardTheme; loaded: boolean } | null = null;
const _subscribers = new Set<() => void>();

function notify() {
  _subscribers.forEach((cb) => cb());
}

async function loadFromServer(): Promise<ChartCardTheme> {
  try {
    const res = await fetch("/api/me/preferences", { cache: "no-store" });
    if (!res.ok) return { ...DEFAULT_THEME };
    const env: PreferencesEnvelope = await res.json();
    if (!env.preferences) return { ...DEFAULT_THEME };
    const parsed = JSON.parse(env.preferences) as Record<string, unknown>;
    const themePart = (parsed[PREF_KEY] ?? null) as Partial<ChartCardTheme> | null;
    if (!themePart) return { ...DEFAULT_THEME };
    return { ...DEFAULT_THEME, ...themePart };
  } catch {
    return { ...DEFAULT_THEME };
  }
}

async function saveToServer(theme: ChartCardTheme): Promise<void> {
  // Read existing prefs first so we don't clobber other keys (future:
  // dashboard_layout, notification_pref, etc.).
  let existing: Record<string, unknown> = {};
  try {
    const res = await fetch("/api/me/preferences", { cache: "no-store" });
    if (res.ok) {
      const env: PreferencesEnvelope = await res.json();
      if (env.preferences) {
        try { existing = JSON.parse(env.preferences); } catch { existing = {}; }
      }
    }
  } catch { /* fall through with empty */ }

  const merged = { ...existing, [PREF_KEY]: theme };
  const res = await fetch("/api/me/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preferences: JSON.stringify(merged) }),
  });
  if (!res.ok) {
    throw new Error(`save failed: ${res.status}`);
  }
}

export function useUserChartTheme() {
  // Initialise from cache if available, else default + trigger fetch.
  const [theme, setThemeState] = useState<ChartCardTheme>(
    _cache?.theme ?? { ...DEFAULT_THEME }
  );
  const [loading, setLoading] = useState(!_cache?.loaded);

  useEffect(() => {
    // Subscribe to cache updates so all hook instances re-sync after save.
    const cb = () => {
      if (_cache) setThemeState(_cache.theme);
    };
    _subscribers.add(cb);
    return () => { _subscribers.delete(cb); };
  }, []);

  useEffect(() => {
    if (_cache?.loaded) return;
    let cancelled = false;
    loadFromServer().then((t) => {
      if (cancelled) return;
      _cache = { theme: t, loaded: true };
      setThemeState(t);
      setLoading(false);
      notify();
    });
    return () => { cancelled = true; };
  }, []);

  const saveAsDefault = useCallback(async (next: ChartCardTheme) => {
    await saveToServer(next);
    _cache = { theme: next, loaded: true };
    notify();
  }, []);

  return { theme, loading, saveAsDefault };
}

/** Test / dev helper to clear the in-memory cache (force re-fetch). */
export function _resetUserChartThemeCache() {
  _cache = null;
}
