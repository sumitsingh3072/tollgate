"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { formatLatencyBin, formatLatencyBinShort } from "@/lib/format";
import type { LatencyBin } from "@/lib/types";

const config = { count: { label: "Requests", color: "var(--chart-1)" } } satisfies ChartConfig;

/** Distribution of upstream response times (cache hits excluded): one hue, magnitude only. */
export function LatencyHistogram({ bins }: { bins: LatencyBin[] }) {
  const data = bins.map((b) => ({
    label: formatLatencyBin(b.lower_ms, b.upper_ms),
    tick: formatLatencyBinShort(b.lower_ms, b.upper_ms),
    count: b.count,
  }));
  if (data.every((d) => d.count === 0)) {
    return <p className="py-10 text-center text-muted-foreground">No upstream-served requests in this window.</p>;
  }
  return (
    <ChartContainer config={config} className="h-52 w-full">
      <BarChart data={data} margin={{ left: 0, right: 4, top: 8 }}>
        <CartesianGrid vertical={false} />
        {/* Compact ticks: 9 bins share half a panel; the tooltip shows the full range. */}
        <XAxis dataKey="tick" tickLine={false} axisLine={false} fontSize={10} interval={0} tickMargin={6} />
        <YAxis tickLine={false} axisLine={false} width={32} fontSize={11} allowDecimals={false} />
        <ChartTooltip
          cursor={{ fill: "var(--muted)" }}
          content={
            <ChartTooltipContent hideIndicator labelFormatter={(_, payload) => payload?.[0]?.payload?.label} />
          }
        />
        <Bar dataKey="count" fill="var(--color-count)" radius={[4, 4, 0, 0]} maxBarSize={40} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}
