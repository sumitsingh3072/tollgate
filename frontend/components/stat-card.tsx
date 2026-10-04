import { ArrowDownRightIcon, ArrowUpRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Sparkline } from "@/components/sparkline";
import { formatChange } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Delta = {
  ratio: number | null;
  /** Which direction is good news; "neutral" keeps the delta uncolored. */
  goodWhen: "up" | "down" | "neutral";
  label: string;
};

function DeltaBadge({ delta }: { delta: Delta }) {
  if (delta.ratio === null) return <span className="text-xs text-muted-foreground">—</span>;
  const up = delta.ratio >= 0;
  const tone =
    delta.goodWhen === "neutral" || Math.abs(delta.ratio) < 0.005
      ? "text-muted-foreground"
      : (delta.goodWhen === "up") === up
        ? "text-success"
        : "text-destructive";
  const Icon = up ? ArrowUpRightIcon : ArrowDownRightIcon;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular-nums", tone)} title={delta.label}>
      <Icon className="size-3.5" aria-hidden />
      {formatChange(delta.ratio)}
      <span className="sr-only">{delta.label}</span>
    </span>
  );
}

export function StatCard({
  label,
  value,
  hint,
  delta,
  trend,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  delta?: Delta;
  trend?: number[];
  tone?: "default" | "warning" | "destructive";
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-card px-4 pt-3 pb-2">
      <span className="truncate text-xs text-muted-foreground">{label}</span>
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={cn(
            "text-2xl font-semibold tracking-tight tabular-nums",
            tone === "warning" && "text-warning",
            tone === "destructive" && "text-destructive",
          )}
        >
          {value}
        </span>
        {delta && <DeltaBadge delta={delta} />}
      </div>
      {hint && <span className="truncate text-xs text-muted-foreground tabular-nums">{hint}</span>}
      {trend && <Sparkline values={trend} />}
    </div>
  );
}
