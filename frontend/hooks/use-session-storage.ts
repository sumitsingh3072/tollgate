"use client";

import { useCallback, useSyncExternalStore } from "react";

// sessionStorage-backed state: survives reloads in this tab, gone when the tab closes.
const EVENT = "tollgate:session-storage";

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
}

function read(key: string): string {
  try {
    return sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export function useSessionStorage(key: string): [string, (value: string) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => "",
  );
  const setValue = useCallback(
    (next: string) => {
      try {
        if (next) sessionStorage.setItem(key, next);
        else sessionStorage.removeItem(key);
      } catch {
        // storage blocked; value just won't persist
      }
      window.dispatchEvent(new Event(EVENT));
    },
    [key],
  );
  return [value, setValue];
}
