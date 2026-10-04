"use client";

import { useSyncExternalStore } from "react";

const noopSubscribe = () => () => {};

function utc(iso: string): string {
  return `${iso.slice(0, 19).replace("T", " ")} UTC`;
}

function local(iso: string, withDate: boolean): string {
  return new Date(iso).toLocaleString(undefined, {
    ...(withDate ? { month: "short", day: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** Viewer-local timestamp. The server renders UTC; the browser swaps in local time without a hydration error. */
export function LocalTime({ iso, withDate = true }: { iso: string; withDate?: boolean }) {
  const text = useSyncExternalStore(
    noopSubscribe,
    () => local(iso, withDate),
    () => utc(iso),
  );
  return (
    <time dateTime={iso} title={utc(iso)} className="tabular-nums">
      {text}
    </time>
  );
}
