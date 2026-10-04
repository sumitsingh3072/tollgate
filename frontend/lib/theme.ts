"use client";

import { useSyncExternalStore } from "react";

import { DARK_QUERY, THEME_STORAGE_KEY } from "@/lib/theme-config";

// Tiny theme store: class="dark" on <html>, persisted in localStorage, follows the OS when "system".
// The first paint is handled by <ThemeScript /> (components/theme-script.tsx).

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const listeners = new Set<() => void>();

function readTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function readResolved(): ResolvedTheme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function apply(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia(DARK_QUERY).matches);
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // storage blocked (private mode); theme still applies for this page view
  }
  apply(theme);
  emit();
}

let detachGlobal: (() => void) | undefined;

function attachGlobal(): () => void {
  const media = window.matchMedia(DARK_QUERY);
  const onSystemChange = () => {
    if (readTheme() === "system") {
      apply("system");
      emit();
    }
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY) {
      apply(readTheme());
      emit();
    }
  };
  media.addEventListener("change", onSystemChange);
  window.addEventListener("storage", onStorage);
  return () => {
    media.removeEventListener("change", onSystemChange);
    window.removeEventListener("storage", onStorage);
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  detachGlobal ??= attachGlobal();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      detachGlobal?.();
      detachGlobal = undefined;
    }
  };
}

export function useTheme(): { theme: Theme; resolvedTheme: ResolvedTheme | undefined; setTheme: typeof setTheme } {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "system" as const);
  const resolvedTheme = useSyncExternalStore(subscribe, readResolved, () => undefined);
  return { theme, resolvedTheme, setTheme };
}
