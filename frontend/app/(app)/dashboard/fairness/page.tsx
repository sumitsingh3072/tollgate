import { Suspense } from "react";

import { AutoRefresh } from "@/components/auto-refresh";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";

import { FairnessContent } from "./fairness-content";

export default function FairnessPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Fairness"
        description="Model slots are shared by a Virtual Token Counter: the key that has received the least service goes next."
        actions={<AutoRefresh seconds={5} />}
      />
      <Suspense fallback={<Skeleton className="h-96 rounded-lg" />}>
        <FairnessContent />
      </Suspense>
    </div>
  );
}
