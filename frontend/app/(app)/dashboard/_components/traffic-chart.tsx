"use client";

import { useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMounted } from "@/hooks/use-mounted";
import { formatCompact, formatLatency } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

type Metric = "requests" | "tokens" | "latency";

const REQUESTS: ChartConfig = {
  served: { label: "Served by model", color: "var(--chart-1)" },
  cached: { label: "Cache hits", color: "var(--chart-2)" },
  errors: { label: "Errors", color: "var(--destructive)" },
};
const TOKENS: ChartConfig = {
  input: { label: "Input tokens", color: "var(--chart-1)" },
  output: { label: "Output tokens", color: "var(--chart-2)" },
};
const LATENCY: ChartConfig = { latency: { label: "Avg latency (served)", color: "var(--chart-1)" } };

const HEIGHT = 240;

function timeFormatter(bucketSeconds: number) {
  const daily = bucketSeconds >= 86_400;
  const tick = new Intl.DateTimeFormat(undefined, daily ? { month: "short", day: "numeric" } : { hour: "2-digit", minute: "2-digit", hour12: false });
  const full = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", ...(daily ? {} : { hour: "2-digit", minute: "2-digit", hour12: false }) });
  return { tick: (ts: string) => tick.format(new Date(ts)), full: (ts: string) => full.format(new Date(ts)) };
}

/** Requests / tokens / latency over the selected window. Rendered after mount: ticks use the viewer's time zone. */
export function TrafficChart({ series, bucketSeconds }: { series: SeriesPoint[]; bucketSeconds: number }) {
  const [metric, setMetric] = useState<Metric>("requests");
  const mounted = useMounted();
  const fmt = timeFormatter(bucketSeconds);

  const data = series.map((p) => ({
    ts: p.ts,
    served: Math.max(p.requests - p.cache_hits - p.errors, 0),
    cached: p.cache_hits,
    errors: p.errors,
    input: p.in_tokens,
    output: p.out_tokens,
    latency: p.avg_latency_ms,
  }));

  const xAxis = (
    <XAxis
      dataKey="ts"
      tickLine={false}
      axisLine={false}
      tickMargin={8}
      minTickGap={32}
      tickFormatter={fmt.tick}
      fontSize={11}
    />
  );
  const tooltip = (format?: (v: number) => string) => (
    <ChartTooltip
      cursor={{ fill: "var(--muted)", stroke: "var(--border)" }}
      content={
        <ChartTooltipContent
          labelFormatter={(_, payload) => fmt.full(String(payload?.[0]?.payload?.ts ?? ""))}
          formatter={format ? (value, name, item) => (
            <div className="flex w-full items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2.5 rounded-[2px]" style={{ background: item.color }} />
                {LATENCY[String(name)]?.label ?? name}
              </span>
              <span className="font-mono tabular-nums text-foreground">{format(Number(value))}</span>
            </div>
          ) : undefined}
        />
      }
    />
  );

  return (
    <Tabs value={metric} onValueChange={(v) => setMetric(v as Metric)} className="gap-3">
      <TabsList>
        <TabsTrigger value="requests">Requests</TabsTrigger>
        <TabsTrigger value="tokens">Tokens</TabsTrigger>
        <TabsTrigger value="latency">Latency</TabsTrigger>
      </TabsList>
      {!mounted ? (
        <Skeleton style={{ height: HEIGHT }} />
      ) : metric === "latency" ? (
        <ChartContainer config={LATENCY} className="w-full" style={{ height: HEIGHT }}>
          <AreaChart data={data} margin={{ left: 4, right: 8, top: 8 }}>
            <defs>
              <linearGradient id="latency-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-latency)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="var(--color-latency)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} />
            {xAxis}
            <YAxis tickLine={false} axisLine={false} width={56} fontSize={11} tickFormatter={(v: number) => formatLatency(v)} />
            {tooltip(formatLatency)}
            <Area
              dataKey="latency"
              type="monotone"
              stroke="var(--color-latency)"
              strokeWidth={2}
              fill="url(#latency-fill)"
              connectNulls
              isAnimationActive={false}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            />
          </AreaChart>
        </ChartContainer>
      ) : (
        <ChartContainer config={metric === "requests" ? REQUESTS : TOKENS} className="w-full" style={{ height: HEIGHT }}>
          <BarChart data={data} margin={{ left: 4, right: 8, top: 8 }} barCategoryGap="20%">
            <CartesianGrid vertical={false} />
            {xAxis}
            <YAxis tickLine={false} axisLine={false} width={48} fontSize={11} tickFormatter={formatCompact} allowDecimals={false} />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            {Object.keys(metric === "requests" ? REQUESTS : TOKENS).map((key, i, all) => (
              <Bar
                key={key}
                dataKey={key}
                stackId="total"
                fill={`var(--color-${key})`}
                stroke="var(--card)"
                strokeWidth={1}
                radius={i === all.length - 1 ? [4, 4, 0, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ChartContainer>
      )}
    </Tabs>
  );
}
