import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";

import { CreateKeyDialog } from "./_components/create-key-dialog";
import { KeysTable, KeysTableSkeleton } from "./_components/keys-table";

export default function KeysPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Keys"
        description="Each key has its own requests-per-minute limit and daily token quota (UTC)."
        actions={<CreateKeyDialog />}
      />
      <Suspense fallback={<KeysTableSkeleton />}>
        <KeysTable />
      </Suspense>
    </div>
  );
}
