"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { formatCompact } from "@/lib/format";

export type UsageDatum = { label: string; value: number };

/** Horizontal bar chart in the theme's chart color; height grows with the number of rows. */
export function UsageChart({ data, metric, color = "var(--chart-1)" }: { data: UsageDatum[]; metric: string; color?: string }) {
  const config = { value: { label: metric, color } } satisfies ChartConfig;
  const height = Math.max(120, data.length * 36 + 24);

  return (
    <ChartContainer config={config} className="w-full" style={{ height }}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 16, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={formatCompact} fontSize={11} />
        <YAxis
          type="category"
          dataKey="label"
          tickLine={false}
          axisLine={false}
          width={128}
          fontSize={12}
          tickFormatter={(v: string) => (v.length > 18 ? `${v.slice(0, 17)}…` : v)}
        />
        <ChartTooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltipContent hideIndicator />} />
        <Bar dataKey="value" fill="var(--color-value)" radius={4} maxBarSize={22} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}
