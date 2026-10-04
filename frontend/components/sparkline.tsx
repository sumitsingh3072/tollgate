"use client";

import { useId } from "react";
import { Area, AreaChart } from "recharts";

import { type ChartConfig, ChartContainer } from "@/components/ui/chart";

const config = { value: { label: "Trend", color: "var(--chart-1)" } } satisfies ChartConfig;

/** Decorative trend line for stat tiles; the tile's number carries the value. */
export function Sparkline({ values }: { values: number[] }) {
  const fillId = `spark-${useId().replace(/:/g, "")}`;
  if (values.length < 2 || values.every((v) => v === 0)) return <div className="h-8" aria-hidden />;
  const data = values.map((value, i) => ({ i, value }));
  return (
    <ChartContainer config={config} className="h-8 w-full" initialDimension={{ width: 160, height: 32 }} aria-hidden>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-value)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="var(--color-value)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          dataKey="value"
          type="monotone"
          stroke="var(--color-value)"
          strokeWidth={1.5}
          fill={`url(#${fillId})`}
          isAnimationActive={false}
          dot={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}
