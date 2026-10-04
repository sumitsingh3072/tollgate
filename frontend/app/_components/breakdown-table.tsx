import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCompact, formatLatency, formatNumber, formatPercent } from "@/lib/format";
import type { GroupUsage } from "@/lib/types";

/** Per-alias or per-model breakdown with an inline share-of-requests bar. */
export function BreakdownTable({ rows, label, emptyName }: { rows: GroupUsage[]; label: string; emptyName: string }) {
  const total = rows.reduce((sum, r) => sum + r.requests, 0);
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>{label}</TableHead>
          <TableHead className="w-[38%]">Share of requests</TableHead>
          <TableHead className="text-right">Tokens</TableHead>
          <TableHead className="text-right">Avg latency</TableHead>
          <TableHead className="text-right">Errors</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const share = total ? row.requests / total : 0;
          return (
            <TableRow key={row.name ?? "__none__"}>
              <TableCell className="font-mono text-xs">{row.name ?? <span className="text-muted-foreground">{emptyName}</span>}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-chart-1" style={{ width: `${share * 100}%` }} />
                  </div>
                  <span className="w-20 text-right text-xs text-muted-foreground tabular-nums">
                    {formatNumber(row.requests)} · {formatPercent(share)}
                  </span>
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatCompact(row.tokens)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatLatency(row.avg_latency_ms)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {row.errors ? <span className="text-destructive">{formatPercent(row.errors / row.requests)}</span> : "0%"}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
