// Display formatting shared by server and client components (locale fixed to avoid hydration drift).

const LOCALE = "en-US";
const integer = new Intl.NumberFormat(LOCALE);
const compact = new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 });

export function formatNumber(value: number): string {
  return integer.format(value);
}

export function formatCompact(value: number): string {
  return value < 10_000 ? integer.format(value) : compact.format(value);
}

export function formatPercent(ratio: number): string {
  return `${(ratio * 100).toFixed(ratio > 0 && ratio < 0.1 ? 1 : 0)}%`;
}

export function formatLatency(ms: number | null): string {
  if (ms === null) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

export function formatWindow(hours: number): string {
  return hours <= 48 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

/** Relative change vs a previous value; null when there is no baseline. */
export function change(current: number | null, previous: number | null): number | null {
  if (current === null || previous === null || previous === 0) return null;
  return (current - previous) / previous;
}

export function formatChange(ratio: number): string {
  const pct = Math.abs(ratio) * 100;
  return `${ratio >= 0 ? "+" : "−"}${pct >= 10 ? pct.toFixed(0) : pct.toFixed(1)}%`;
}

export function formatLatencyBin(lower: number, upper: number | null): string {
  const unit = (ms: number) => (ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`);
  const bare = (ms: number, inSeconds: boolean) => (inSeconds ? `${ms / 1000}` : `${ms}`);
  if (upper === null) return `≥${unit(lower)}`;
  if (lower === 0) return `<${unit(upper)}`;
  const inSeconds = upper >= 1000;
  return `${bare(lower, inSeconds)}–${unit(upper)}`;
}

/** UTC calendar day ("2026-10-04") -> "Oct 4", independent of the viewer's time zone. */
export function formatDay(date: string, withYear = false): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(LOCALE, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" } : {}),
  });
}
