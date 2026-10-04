import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { RefreshButton } from "@/components/refresh-button";
import { WindowSelect } from "@/components/window-select";
import { intParam } from "@/lib/search-params";

import { OverviewContent, OverviewSkeleton } from "./_components/overview";

const WINDOW_HOURS = [24, 168, 720] as const;

export default async function OverviewPage({ searchParams }: PageProps<"/dashboard">) {
  const hours = intParam(await searchParams, "hours", WINDOW_HOURS) ?? 24;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description="Traffic, tokens, cache hit rate and latency across all keys."
        actions={
          <>
            <WindowSelect hours={hours} />
            <RefreshButton />
          </>
        }
      />
      <Suspense key={hours} fallback={<OverviewSkeleton />}>
        <OverviewContent hours={hours} />
      </Suspense>
    </div>
  );
}
