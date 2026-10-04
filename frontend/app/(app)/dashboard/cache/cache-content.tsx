import { CircleCheckIcon, EyeOffIcon, HardDriveIcon, RadioIcon, ShieldIcon, SparklesIcon } from "lucide-react";

import { Meter } from "@/components/meter";
import { Panel } from "@/components/panel";
import { StatCard } from "@/components/stat-card";
import { formatBytes, formatNumber, formatPercent, formatWindow } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { CacheStats } from "@/lib/types";

// What each outcome means, in the order a request can meet them.
const OUTCOMES = [
  { key: "hit", label: "Hit", hint: "Served from cache; no model call", color: "var(--chart-2)" },
  { key: "miss", label: "Stored", hint: "Answered by the model and cached for next time", color: "var(--chart-1)" },
  { key: "admission_rejected", label: "Seen once", hint: "First sighting: only a small marker kept", color: "var(--chart-3)" },
  { key: "ineligible", label: "Not cacheable", hint: "Non-deterministic, cut off, tool calls or too large", color: "var(--muted-foreground)" },
  { key: "bypass", label: "Bypassed", hint: "Not considered for caching", color: "var(--border)" },
] as const;

const LAYERS = [
  { icon: CircleCheckIcon, title: "Only deterministic, complete answers", body: "temperature 0, finish_reason \"stop\", no tool calls, under the size cap." },
  { icon: SparklesIcon, title: "Admitted on second sight", body: "One-off prompts never take space: the first sighting leaves a ~100 byte marker; the answer is stored when the prompt returns." },
  { icon: HardDriveIcon, title: "Bounded memory, LFU eviction", body: "A separate Redis with a memory cap evicts the least-frequently-used entries, so limits and quotas are never evicted." },
  { icon: ShieldIcon, title: "Private by default", body: "Entries are scoped to the API key. Shared pools are opt-in per alias, with per-key insert budgets." },
  { icon: RadioIcon, title: "Streams too", body: "Streamed answers are cached as they pass through and replayed as a fast stream." },
  { icon: EyeOffIcon, title: "No hints in shared pools", body: "Cache headers are hidden in shared scope. Response timing can still leak, which is why sharing is opt-in." },
];

export async function CacheContent({ hours }: { hours: number }) {
  const stats = await admin<CacheStats>(`/cache/stats?hours=${hours}`);
  const window = formatWindow(hours);
  const total = Object.values(stats.statuses).reduce((a, b) => a + b, 0);
  const operator = stats.entries !== null; // instance-wide figures are hidden from signed-in users
  const used = stats.used_memory_bytes ?? 0;
  const limit = stats.max_memory_bytes ?? 0;
  const memoryKnown = used > 0;
  const n = (value: number | null) => (value === null ? "—" : formatNumber(value));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Hit rate" value={formatPercent(stats.hit_rate)} hint={`of cacheable requests, ${window}`} />
        <StatCard
          label="Entries stored"
          value={n(stats.entries)}
          hint={operator ? `${n(stats.seen_markers)} seen-once markers` : "operator view only"}
        />
        <StatCard
          label="Memory"
          value={memoryKnown ? formatBytes(used) : "—"}
          hint={!operator ? "operator view only" : limit ? `of ${formatBytes(limit)} limit` : "no limit set"}
        />
        <StatCard label="Evictions" value={n(stats.evicted_keys)} hint="since the cache started" />
        <StatCard label="Kept out" value={formatNumber(stats.admission_rejected)} hint="one-off prompts not stored" />
        <StatCard label="Hits per MB" value={stats.hits_per_mb === null ? "—" : formatNumber(Math.round(stats.hits_per_mb))} hint="memory efficiency" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Outcomes" description={`What happened to every request, last ${window}`}>
          {total === 0 ? (
            <p className="py-8 text-center text-muted-foreground">No requests in this window.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                {OUTCOMES.filter((o) => stats.statuses[o.key]).map((o) => (
                  <div key={o.key} style={{ width: `${(stats.statuses[o.key] / total) * 100}%`, background: o.color }} />
                ))}
              </div>
              <ul className="space-y-2">
                {OUTCOMES.map((o) => (
                  <li key={o.key} className="flex items-center gap-2">
                    <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: o.color }} aria-hidden />
                    <span className="w-28 shrink-0">{o.label}</span>
                    <span className="flex-1 truncate text-xs text-muted-foreground">{o.hint}</span>
                    <span className="w-14 text-right font-medium tabular-nums">{formatNumber(stats.statuses[o.key] ?? 0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>

        <Panel title="Memory" description="The cache runs in its own Redis so it can never evict limits or quotas">
          <div className="space-y-4">
            {limit > 0 && memoryKnown ? (
              <div className="space-y-2">
                <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
                  <span>{formatBytes(used)} used</span>
                  <span>
                    {formatPercent(used / limit)} of {formatBytes(limit)}
                  </span>
                </div>
                <Meter value={used} max={limit} label="Cache memory used" />
              </div>
            ) : (
              <p className="text-muted-foreground">
                {operator ? "No memory limit reported." : "Memory figures are shown to the operator only."}
              </p>
            )}
            <dl className="grid grid-cols-2 gap-3 text-[13px]">
              <div>
                <dt className="text-xs text-muted-foreground">Eviction policy</dt>
                <dd className="font-mono">{stats.eviction_policy ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Instance</dt>
                <dd>
                  {stats.separate_instance === null
                    ? "—"
                    : stats.separate_instance
                      ? "Dedicated cache Redis"
                      : "Shared with state (dev)"}
                </dd>
              </div>
            </dl>
          </div>
        </Panel>
      </div>

      <Panel title="How the cache stays small" description="Most prompts never repeat; storing them would push out the ones that do">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {LAYERS.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-background text-primary">
                <Icon className="size-4" />
              </span>
              <div>
                <p className="font-medium">{title}</p>
                <p className="text-xs text-muted-foreground">{body}</p>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
