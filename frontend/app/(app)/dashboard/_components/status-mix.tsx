import { CircleCheckIcon, CircleSlashIcon, OctagonXIcon, TimerIcon } from "lucide-react";

import { formatNumber, formatPercent } from "@/lib/format";
import type { StatusMix as StatusMixData } from "@/lib/types";

// Status colors are reserved for state and always paired with an icon + label.
const ROWS = [
  { key: "success", label: "Success (2xx)", color: "var(--success)", icon: CircleCheckIcon },
  { key: "rate_limited", label: "Rate limited (429)", color: "var(--warning)", icon: TimerIcon },
  { key: "client_errors", label: "Client errors (4xx)", color: "var(--serious)", icon: CircleSlashIcon },
  { key: "server_errors", label: "Server errors (5xx)", color: "var(--destructive)", icon: OctagonXIcon },
] as const;

/** Part-to-whole as one stacked bar, with exact counts listed underneath. */
export function StatusMix({ mix }: { mix: StatusMixData }) {
  const total = ROWS.reduce((sum, r) => sum + mix[r.key], 0);
  return (
    <div className="space-y-4">
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        {ROWS.filter((r) => mix[r.key] > 0).map((r) => (
          <div key={r.key} style={{ width: `${(mix[r.key] / total) * 100}%`, background: r.color }} />
        ))}
      </div>
      <ul className="space-y-2">
        {ROWS.map(({ key, label, color, icon: Icon }) => (
          <li key={key} className="flex items-center gap-2">
            <Icon className="size-4 shrink-0" style={{ color }} aria-hidden />
            <span className="flex-1">{label}</span>
            <span className="tabular-nums text-muted-foreground">{total ? formatPercent(mix[key] / total) : "—"}</span>
            <span className="w-14 text-right font-medium tabular-nums">{formatNumber(mix[key])}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
