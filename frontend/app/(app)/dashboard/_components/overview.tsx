import { BarChart3Icon } from "lucide-react";
import Link from "next/link";

import { Panel } from "@/components/panel";
import { type Delta, StatCard } from "@/components/stat-card";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageChart } from "@/components/usage-chart";
import { change, formatCompact, formatLatency, formatNumber, formatPercent, formatWindow } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { ActivityDay, SeriesPoint, Stats } from "@/lib/types";

import { ActivityHeatmap } from "./activity-heatmap";
import { BreakdownTable } from "./breakdown-table";
import { LatencyHistogram } from "./latency-histogram";
import { StatusMix } from "./status-mix";
import { TrafficChart } from "./traffic-chart";

const ratio = (part: number, whole: number) => (whole ? part / whole : 0);

/** Per-bucket trends for the stat tile sparklines. Latency gaps carry the last value forward. */
function trends(series: SeriesPoint[]) {
  let lastLatency = 0;
  return {
    requests: series.map((p) => p.requests),
    tokens: series.map((p) => p.in_tokens + p.out_tokens),
    cacheRate: series.map((p) => ratio(p.cache_hits, p.requests)),
    errorRate: series.map((p) => ratio(p.errors, p.requests)),
    latency: series.map((p) => (lastLatency = p.avg_latency_ms ?? lastLatency)),
    fallbacks: series.map((p) => p.fallbacks),
  };
}

export async function OverviewContent({ hours }: { hours: number }) {
  const [stats, activity] = await Promise.all([
    admin<Stats>(`/stats?hours=${hours}`),
    admin<ActivityDay[]>("/activity?days=365"),
  ]);
  const window = formatWindow(hours);
  const vs = `vs previous ${window}`;

  if (stats.requests === 0 && activity.every((d) => d.requests === 0)) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BarChart3Icon />
          </EmptyMedia>
          <EmptyTitle>No traffic yet</EmptyTitle>
          <EmptyDescription>Create a key and send a request from the Playground to see it here.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="flex-row justify-center gap-2">
          <Button size="sm" render={<Link href="/dashboard/keys" />}>
            Create a key
          </Button>
          <Button size="sm" variant="outline" render={<Link href="/dashboard/playground" />}>
            Open Playground
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  const prev = stats.previous;
  const tokens = stats.in_tokens + stats.out_tokens;
  const prevTokens = prev.in_tokens + prev.out_tokens;
  const t = trends(stats.series);
  const delta = (current: number | null, previous: number | null, goodWhen: Delta["goodWhen"]): Delta => ({
    ratio: prev.requests ? change(current, previous) : null,
    goodWhen,
    label: vs,
  });
  // Tokens an upstream call would have cost, avoided by serving from cache.
  const servedByUpstream = stats.requests - stats.cache_hits - stats.errors;
  const savedTokens = servedByUpstream > 0 ? Math.round((tokens / servedByUpstream) * stats.cache_hits) : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Requests"
          value={formatCompact(stats.requests)}
          hint={`last ${window}`}
          delta={delta(stats.requests, prev.requests, "neutral")}
          trend={t.requests}
        />
        <StatCard
          label="Tokens"
          value={formatCompact(tokens)}
          hint={`${formatCompact(stats.in_tokens)} in · ${formatCompact(stats.out_tokens)} out`}
          delta={delta(tokens, prevTokens, "neutral")}
          trend={t.tokens}
        />
        <StatCard
          label="Cache hit rate"
          value={formatPercent(stats.cache_hit_rate)}
          hint={savedTokens ? `~${formatCompact(savedTokens)} tokens saved` : `${formatNumber(stats.cache_hits)} hits`}
          delta={delta(stats.cache_hit_rate, prev.cache_hit_rate, "up")}
          trend={t.cacheRate}
        />
        <StatCard
          label="Error rate"
          value={formatPercent(stats.error_rate)}
          hint={`${formatNumber(stats.errors)} errors`}
          tone={stats.error_rate >= 0.05 ? "destructive" : stats.error_rate > 0 ? "warning" : "default"}
          delta={delta(stats.error_rate, prev.error_rate, "down")}
          trend={t.errorRate}
        />
        <StatCard
          label="Latency p50"
          value={formatLatency(stats.p50_latency_ms)}
          hint={`p95 ${formatLatency(stats.p95_latency_ms)}`}
          delta={delta(stats.p50_latency_ms, prev.p50_latency_ms, "down")}
          trend={t.latency}
        />
        <StatCard
          label="Time to first token"
          value={formatLatency(stats.p50_ttft_ms)}
          hint={stats.p95_ttft_ms === null ? "streams only" : `p95 ${formatLatency(stats.p95_ttft_ms)} · streams`}
        />
        <StatCard
          label="Model calls saved"
          value={formatNumber(stats.coalesced + stats.cache_hits)}
          hint={`${formatNumber(stats.cache_hits)} cache · ${formatNumber(stats.coalesced)} coalesced`}
        />
        <StatCard
          label="Fallbacks"
          value={formatNumber(stats.fallbacks)}
          hint="served by a backup model"
          delta={delta(stats.fallbacks, prev.fallbacks, "down")}
          trend={t.fallbacks}
        />
      </div>

      <Panel title="Traffic" description={`Last ${window}, ${stats.bucket_seconds >= 86_400 ? "daily" : `${stats.bucket_seconds / 3600}-hour`} buckets`}>
        <TrafficChart series={stats.series} bucketSeconds={stats.bucket_seconds} />
      </Panel>

      <Panel title="Activity" description="Daily usage over the past year">
        <ActivityHeatmap days={activity} />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Status mix" description={`Outcome of every request, last ${window}`}>
          <StatusMix mix={stats.status_mix} />
        </Panel>
        <Panel title="Latency distribution" description="Upstream response times (cache hits excluded)">
          <LatencyHistogram bins={stats.latency_histogram} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Tokens by key" description={`Upstream tokens consumed per key, last ${window}`}>
          <UsageChart data={stats.by_key.map((k) => ({ label: k.name ?? k.prefix ?? "unknown", value: k.tokens }))} metric="Tokens" />
        </Panel>
        <Panel title="Models" description="Which upstream model actually served each request" flush>
          <BreakdownTable rows={stats.by_model} label="Model" emptyName="rejected (no model)" />
        </Panel>
      </div>

      <Panel title="Aliases" description={`What clients asked for, last ${window}`} flush>
        <BreakdownTable rows={stats.by_alias} label="Alias" emptyName="unknown" />
      </Panel>
    </div>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading overview">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-[118px] rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-80 rounded-lg" />
      <Skeleton className="h-56 rounded-lg" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    </div>
  );
}
