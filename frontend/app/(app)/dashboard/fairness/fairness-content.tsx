import { ScaleIcon } from "lucide-react";

import { Meter } from "@/components/meter";
import { Panel } from "@/components/panel";
import { StatCard } from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCompact, formatLatency, formatNumber, formatPercent } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { Fairness } from "@/lib/types";

const MODE_LABEL: Record<Fairness["mode"], string> = {
  fair: "Fair (VTC)",
  fifo: "FIFO (benchmark)",
  off: "Off: provider queue (benchmark)",
};

export async function FairnessContent() {
  const data = await admin<Fairness>("/fairness?hours=1");
  const queuedNow = data.models.reduce((n, m) => n + m.queued, 0);
  const running = data.models.reduce((n, m) => n + m.running, 0);
  const slots = data.models.reduce((n, m) => n + m.parallel, 0);
  const worstWait = Math.max(0, ...data.keys.map((k) => k.queue_wait_p95_ms ?? 0));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Jain's fairness index"
          value={data.jain_index === null ? "—" : data.jain_index.toFixed(2)}
          hint="1.00 = tokens shared evenly, last hour"
        />
        <StatCard label="Active keys" value={formatNumber(data.keys.length)} hint="sent traffic in the last hour" />
        <StatCard label="Running / waiting" value={`${running} / ${queuedNow}`} hint={slots ? `${slots} model slots in total` : "no model used yet"} />
        <StatCard label="Worst wait p95" value={worstWait ? formatLatency(worstWait) : "—"} hint="slowest key's queue wait" />
      </div>

      <Panel
        title="Model slots"
        description="In-flight requests per upstream model; extra requests wait in Tollgate's queue"
        actions={<Badge variant="outline">{MODE_LABEL[data.mode]}</Badge>}
        flush={data.models.length > 0}
      >
        {data.models.length === 0 ? (
          <p className="text-muted-foreground">No upstream model has been called since the gateway started.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Model</TableHead>
                <TableHead className="w-1/3">Slots in use</TableHead>
                <TableHead className="text-right">Waiting</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.models.map((m) => (
                <TableRow key={m.model}>
                  <TableCell className="font-mono text-xs">{m.model}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="flex-1">
                        <Meter value={m.running} max={m.parallel} label={`${m.model} slots in use`} />
                      </div>
                      <span className="w-12 text-right text-xs text-muted-foreground tabular-nums">
                        {m.running}/{m.parallel}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{m.queued}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>

      <Panel title="Service by key" description="Tokens served in the last hour, queue waits, and each key's virtual counter" flush={data.keys.length > 0}>
        {data.keys.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ScaleIcon />
              </EmptyMedia>
              <EmptyTitle>No traffic in the last hour</EmptyTitle>
              <EmptyDescription>Send requests from two keys at once to watch the queue share the model.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Key</TableHead>
                <TableHead className="w-1/4">Share of tokens</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Wait p95</TableHead>
                <TableHead className="text-right">Wait avg</TableHead>
                <TableHead className="text-right">Waiting now</TableHead>
                <TableHead className="text-right" title="Virtual Token Counter: input + 2 x output tokens served">
                  Counter
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.keys.map((k) => (
                <TableRow key={k.key_id ?? "none"}>
                  <TableCell>
                    <span className="font-medium">{k.name ?? "unknown"}</span>{" "}
                    <span className="font-mono text-xs text-muted-foreground">{k.prefix}</span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-chart-1" style={{ width: `${k.share * 100}%` }} />
                      </div>
                      <span className="w-24 text-right text-xs text-muted-foreground tabular-nums">
                        {formatCompact(k.tokens)} · {formatPercent(k.share)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(k.requests)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatLatency(k.queue_wait_p95_ms)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatLatency(k.queue_wait_avg_ms)}</TableCell>
                  <TableCell className="text-right tabular-nums">{k.queued_now}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{formatCompact(Math.round(k.virtual_tokens))}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
