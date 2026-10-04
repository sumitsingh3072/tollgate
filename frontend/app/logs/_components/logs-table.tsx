import { ScrollTextIcon } from "lucide-react";
import Link from "next/link";

import { LocalTime } from "@/components/local-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatLatency, formatNumber } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { LogPage, RequestLog } from "@/lib/types";
import { cn } from "@/lib/utils";

import type { LogFilterValues } from "./log-filters";

const PAGE_SIZE = 50;

function gatewayQuery(filters: LogFilterValues, before?: number): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (filters.key) params.set("key_id", filters.key);
  if (filters.alias) params.set("alias", filters.alias);
  if (filters.status === "errors") params.set("errors_only", "true");
  if (filters.status === "429") params.set("status", "429");
  if (before) params.set("before", String(before));
  return params.toString();
}

function pageHref(filters: LogFilterValues, before?: number): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) if (value) params.set(name, value);
  if (before) params.set("before", String(before));
  const query = params.toString();
  return query ? `/logs?${query}` : "/logs";
}

function StatusBadge({ status }: { status: number }) {
  const tone =
    status < 400
      ? "bg-success/12 text-success"
      : status === 429
        ? "bg-warning/15 text-warning"
        : "bg-destructive/12 text-destructive";
  return <Badge className={cn("font-mono tabular-nums", tone)}>{status}</Badge>;
}

function Flags({ log }: { log: RequestLog }) {
  return (
    <div className="flex gap-1">
      {log.cache_hit && <Badge variant="secondary">cache</Badge>}
      {log.fallback_used && <Badge className="bg-chart-3/15 text-chart-3">fallback</Badge>}
    </div>
  );
}

export async function LogsTable({ filters, before }: { filters: LogFilterValues; before?: number }) {
  const page = await admin<LogPage>(`/logs?${gatewayQuery(filters, before)}`);

  if (page.items.length === 0) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ScrollTextIcon />
          </EmptyMedia>
          <EmptyTitle>No requests found</EmptyTitle>
          <EmptyDescription>
            {before ? "No older requests match these filters." : "Requests appear here within a few seconds."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Key</TableHead>
              <TableHead>Alias</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Tokens in / out</TableHead>
              <TableHead className="text-right">Latency</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.items.map((log) => (
              <TableRow key={log.id}>
                <TableCell className="text-muted-foreground">
                  <LocalTime iso={log.ts} />
                </TableCell>
                <TableCell>{log.key_name ?? <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell className="font-mono text-xs">{log.alias}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{log.model_used ?? "—"}</TableCell>
                <TableCell>
                  <StatusBadge status={log.status} />
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatNumber(log.in_tokens)} <span className="text-muted-foreground">/</span>{" "}
                  {formatNumber(log.out_tokens)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatLatency(log.latency_ms)}</TableCell>
                <TableCell>
                  <Flags log={log} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <nav className="flex items-center justify-end gap-2" aria-label="Pagination">
        {before && (
          <Button variant="outline" size="sm" render={<Link href={pageHref(filters)} />}>
            Newest
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={page.next_cursor === null}
          render={page.next_cursor === null ? undefined : <Link href={pageHref(filters, page.next_cursor)} />}
        >
          Older
        </Button>
      </nav>
    </div>
  );
}

export function LogsTableSkeleton() {
  return (
    <div className="space-y-2 rounded-lg border p-3" aria-busy="true" aria-label="Loading logs">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-7" />
      ))}
    </div>
  );
}
