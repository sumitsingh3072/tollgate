import { KeyRoundIcon } from "lucide-react";

import { LocalTime } from "@/components/local-time";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCompact, formatNumber } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { ApiKey } from "@/lib/types";
import { cn } from "@/lib/utils";

import { RevokeKeyButton } from "./revoke-key-button";

function QuotaBar({ used, quota }: { used: number; quota: number }) {
  const ratio = Math.min(used / quota, 1);
  return (
    <div className="flex min-w-36 items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full bg-primary", ratio >= 1 && "bg-destructive", ratio >= 0.8 && ratio < 1 && "bg-warning")}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums">
        {formatCompact(used)} / {formatCompact(quota)}
      </span>
    </div>
  );
}

export async function KeysTable() {
  const keys = await admin<ApiKey[]>("/keys");

  if (keys.length === 0) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <KeyRoundIcon />
          </EmptyMedia>
          <EmptyTitle>No keys yet</EmptyTitle>
          <EmptyDescription>Create a key, then point any OpenAI SDK at the gateway with it.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader className="bg-muted/50">
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Key</TableHead>
            <TableHead className="text-right">RPM</TableHead>
            <TableHead>Tokens today</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-0" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => {
            const revoked = key.revoked_at !== null;
            return (
              <TableRow key={key.id} className={cn(revoked && "text-muted-foreground")}>
                <TableCell className="font-medium">{key.name}</TableCell>
                <TableCell className="font-mono text-xs">{key.prefix}…</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(key.rpm)}</TableCell>
                <TableCell>
                  {revoked ? "—" : <QuotaBar used={key.tokens_today} quota={key.daily_token_quota} />}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  <LocalTime iso={key.created_at} />
                </TableCell>
                <TableCell>
                  {revoked ? <Badge variant="outline">Revoked</Badge> : <Badge variant="secondary">Active</Badge>}
                </TableCell>
                <TableCell>{!revoked && <RevokeKeyButton id={key.id} name={key.name} />}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export function KeysTableSkeleton() {
  return (
    <div className="space-y-2 rounded-lg border p-3" aria-busy="true" aria-label="Loading keys">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-8" />
      ))}
    </div>
  );
}
