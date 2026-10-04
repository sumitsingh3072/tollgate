import { BarChart3Icon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { StatCard } from "@/components/stat-card";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageChart } from "@/components/usage-chart";
import { formatCompact, formatLatency, formatNumber, formatPercent, formatWindow } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { Stats } from "@/lib/types";

function Panel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border bg-card">
      <header className="border-b px-4 py-3">
        <h2 className="font-medium">{title}</h2>
        <p className="text-xs text-muted-foreground">{description}</p>
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export async function OverviewContent({ hours }: { hours: number }) {
  const stats = await admin<Stats>(`/stats?hours=${hours}`);
  const window = formatWindow(hours);

  if (stats.requests === 0) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BarChart3Icon />
          </EmptyMedia>
          <EmptyTitle>No traffic in the last {window}</EmptyTitle>
          <EmptyDescription>Create a key and send a request from the Playground to see it here.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="flex-row justify-center gap-2">
          <Button size="sm" render={<Link href="/keys" />}>
            Create a key
          </Button>
          <Button size="sm" variant="outline" render={<Link href="/playground" />}>
            Open Playground
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  const tokens = stats.in_tokens + stats.out_tokens;
  const byKey = stats.by_key.map((k) => ({ label: k.name ?? k.prefix ?? "unknown", value: k.tokens }));
  const byModel = stats.by_model.map((m) => ({ label: m.model ?? "rejected (no model)", value: m.requests }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Requests" value={formatCompact(stats.requests)} hint={`last ${window}`} />
        <StatCard
          label="Tokens"
          value={formatCompact(tokens)}
          hint={`${formatCompact(stats.in_tokens)} in · ${formatCompact(stats.out_tokens)} out`}
        />
        <StatCard
          label="Cache hit rate"
          value={formatPercent(stats.cache_hit_rate)}
          hint={`${formatNumber(stats.cache_hits)} hits`}
        />
        <StatCard
          label="Error rate"
          value={formatPercent(stats.error_rate)}
          hint={`${formatNumber(stats.errors)} errors`}
          tone={stats.error_rate >= 0.05 ? "destructive" : stats.error_rate > 0 ? "warning" : "default"}
        />
        <StatCard label="Latency p50" value={formatLatency(stats.p50_latency_ms)} hint={`p95 ${formatLatency(stats.p95_latency_ms)}`} />
        <StatCard label="Fallbacks" value={formatNumber(stats.fallbacks)} hint="served by a backup model" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Tokens by key" description={`Upstream tokens consumed per key, last ${window}`}>
          <UsageChart data={byKey} metric="Tokens" />
        </Panel>
        <Panel title="Requests by model" description="Which upstream model actually served each request">
          <UsageChart data={byModel} metric="Requests" color="var(--chart-2)" />
        </Panel>
      </div>
    </div>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading overview">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-[86px] rounded-lg" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    </div>
  );
}
