import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { RefreshButton } from "@/components/refresh-button";
import { Skeleton } from "@/components/ui/skeleton";
import { WindowSelect } from "@/components/window-select";
import { intParam } from "@/lib/search-params";

import { CacheContent } from "./cache-content";

const WINDOW_HOURS = [24, 168, 720] as const;

export default async function CachePage({ searchParams }: PageProps<"/dashboard/cache">) {
  const hours = intParam(await searchParams, "hours", WINDOW_HOURS) ?? 24;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Cache"
        description="Deterministic answers served from memory, without touching the model."
        actions={
          <>
            <WindowSelect hours={hours} />
            <RefreshButton />
          </>
        }
      />
      <Suspense key={hours} fallback={<Skeleton className="h-96 rounded-lg" />}>
        <CacheContent hours={hours} />
      </Suspense>
    </div>
  );
}
