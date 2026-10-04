import { cn } from "@/lib/utils";

/** A single ratio against a limit (same-hue track). Turns warning/destructive near the limit. */
export function Meter({ value, max, label }: { value: number; max: number; label?: string }) {
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  return (
    <div className="space-y-1">
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="meter"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label}
      >
        <div
          className={cn("h-full rounded-full bg-primary", ratio >= 0.9 ? "bg-destructive" : ratio >= 0.75 && "bg-warning")}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}
