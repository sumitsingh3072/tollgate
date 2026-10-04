import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { RefreshButton } from "@/components/refresh-button";
import { admin } from "@/lib/server/gateway";
import { intParam, param, type SearchParams } from "@/lib/search-params";
import type { AliasInfo, ApiKey } from "@/lib/types";

import { LogFilters, type LogFilterValues } from "./_components/log-filters";
import { LogsTable, LogsTableSkeleton } from "./_components/logs-table";

const STATUS_FILTERS = ["errors", "429"] as const;

function readFilters(params: SearchParams): LogFilterValues {
  const status = param(params, "status");
  return {
    key: param(params, "key"),
    alias: param(params, "alias"),
    status: STATUS_FILTERS.find((s) => s === status),
  };
}

export default async function LogsPage({ searchParams }: PageProps<"/logs">) {
  const params = await searchParams;
  const filters = readFilters(params);
  const before = intParam(params, "before");
  const [keys, aliases] = await Promise.all([admin<ApiKey[]>("/keys"), admin<AliasInfo[]>("/aliases")]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Logs"
        description="Every authenticated request, newest first. Streams appear when they finish."
        actions={<RefreshButton />}
      />
      <LogFilters
        values={filters}
        keys={keys.map((k) => ({ value: k.id, label: k.name }))}
        aliases={aliases.map((a) => a.id)}
      />
      <Suspense key={JSON.stringify({ filters, before })} fallback={<LogsTableSkeleton />}>
        <LogsTable filters={filters} before={before} />
      </Suspense>
    </div>
  );
}
