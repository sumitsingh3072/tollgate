"use client";

import { useMemo, useState } from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCompact, formatDay, formatNumber } from "@/lib/format";
import type { ActivityDay } from "@/lib/types";

type Metric = "requests" | "tokens";

// Sequential single hue: empty days use the muted surface, then chart-1 at increasing strength.
const LEVEL_COLORS = [
  "var(--muted)",
  "color-mix(in oklch, var(--chart-1) 30%, var(--muted))",
  "color-mix(in oklch, var(--chart-1) 55%, var(--muted))",
  "color-mix(in oklch, var(--chart-1) 78%, var(--muted))",
  "var(--chart-1)",
];
const WEEKDAY_LABELS = ["", "Mon", "", "Wed", "", "Fri", ""];

/** Quartile thresholds over non-zero days, like GitHub's contribution graph. */
function levelFor(thresholds: number[]) {
  return (value: number) => (value === 0 ? 0 : 1 + thresholds.filter((t) => value > t).length);
}

function quartiles(values: number[]): number[] {
  const nonZero = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (nonZero.length === 0) return [0, 0, 0];
  const at = (q: number) => nonZero[Math.min(nonZero.length - 1, Math.floor(q * nonZero.length))];
  return [at(0.25), at(0.5), at(0.75)];
}

function streaks(days: ActivityDay[]): { longest: number; current: number } {
  let longest = 0;
  let run = 0;
  for (const day of days) {
    run = day.requests > 0 ? run + 1 : 0;
    longest = Math.max(longest, run);
  }
  return { longest, current: run };
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium tabular-nums">{value}</div>
    </div>
  );
}

export function ActivityHeatmap({ days }: { days: ActivityDay[] }) {
  const [metric, setMetric] = useState<Metric>("requests");
  const [hovered, setHovered] = useState<ActivityDay | null>(null);

  const { cells, columns, monthLabels } = useMemo(() => {
    // Pad the first week so every column starts on Sunday (UTC days).
    const pad = days.length ? new Date(`${days[0].date}T00:00:00Z`).getUTCDay() : 0;
    const padded: (ActivityDay | null)[] = [...Array<null>(pad).fill(null), ...days];
    const cols = Math.ceil(padded.length / 7);
    const labels: { col: number; label: string }[] = [];
    let lastMonth = -1;
    for (let col = 0; col < cols; col++) {
      const first = padded.slice(col * 7, col * 7 + 7).find((d) => d !== null);
      if (!first) continue;
      const month = new Date(`${first.date}T00:00:00Z`).getUTCMonth();
      if (month !== lastMonth) {
        labels.push({ col, label: new Date(`${first.date}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" }) });
        lastMonth = month;
      }
    }
    // Drop a label that would collide with the next one (first partial month).
    const spaced = labels.filter((l, i) => i === labels.length - 1 || labels[i + 1].col - l.col >= 3);
    return { cells: padded, columns: cols, monthLabels: spaced };
  }, [days]);

  const values = days.map((d) => d[metric]);
  const level = levelFor(quartiles(values));
  const total = values.reduce((a, b) => a + b, 0);
  const activeDays = days.filter((d) => d.requests > 0).length;
  const busiest = days.reduce<ActivityDay | null>((best, d) => (!best || d[metric] > best[metric] ? d : best), null);
  const { longest, current } = streaks(days);
  const unit = metric === "requests" ? "requests" : "tokens";

  return (
    <Tabs value={metric} onValueChange={(v) => setMetric(v as Metric)} className="gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap gap-x-8 gap-y-2">
          <Summary label={`Total ${unit}`} value={formatNumber(total)} />
          <Summary label="Active days" value={`${activeDays} / ${days.length}`} />
          <Summary label="Longest streak" value={`${longest} ${longest === 1 ? "day" : "days"}`} />
          <Summary label="Current streak" value={`${current} ${current === 1 ? "day" : "days"}`} />
          {busiest && busiest[metric] > 0 && (
            <Summary label="Busiest day" value={`${formatDay(busiest.date)} · ${formatCompact(busiest[metric])}`} />
          )}
        </div>
        <TabsList>
          <TabsTrigger value="requests">Requests</TabsTrigger>
          <TabsTrigger value="tokens">Tokens</TabsTrigger>
        </TabsList>
      </div>

      <div className="overflow-x-auto pb-1">
        {/* Cells stretch to fill the panel (min 9px, square); scrolls horizontally on narrow screens. */}
        <div
          className="grid min-w-[620px] gap-[3px] text-[10px] text-muted-foreground"
          style={{ gridTemplateColumns: `28px repeat(${columns}, minmax(9px, 1fr))` }}
          role="img"
          aria-label={`${formatNumber(total)} ${unit} over the last ${days.length} days, ${activeDays} active days`}
        >
          {/* month labels */}
          <span />
          {Array.from({ length: columns }, (_, col) => (
            <span key={col} className="h-4 overflow-visible whitespace-nowrap">
              {monthLabels.find((l) => l.col === col)?.label ?? ""}
            </span>
          ))}
          {/* weekday labels + cells, row by row */}
          {WEEKDAY_LABELS.map((weekday, row) => [
            <span key={`w${row}`} className="flex items-center leading-none">
              {weekday}
            </span>,
            ...Array.from({ length: columns }, (_, col) => {
              const day = cells[col * 7 + row];
              if (!day) return <span key={`${row}-${col}`} />;
              return (
                <span
                  key={day.date}
                  className="aspect-square w-full rounded-[3px] transition-[background-color,box-shadow] duration-150 hover:ring-1 hover:ring-foreground/50"
                  style={{ background: LEVEL_COLORS[level(day[metric])] }}
                  onMouseEnter={() => setHovered(day)}
                  onMouseLeave={() => setHovered(null)}
                />
              );
            }),
          ])}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="tabular-nums" aria-live="polite">
          {hovered
            ? `${formatDay(hovered.date, true)} · ${formatNumber(hovered.requests)} requests · ${formatCompact(hovered.tokens)} tokens${hovered.errors ? ` · ${hovered.errors} errors` : ""}`
            : "Hover a day for details. Days are UTC."}
        </span>
        <span className="flex items-center gap-1">
          Less
          {LEVEL_COLORS.map((color) => (
            <span key={color} className="size-[11px] rounded-[3px]" style={{ background: color }} />
          ))}
          More
        </span>
      </div>
    </Tabs>
  );
}
