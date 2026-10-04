import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { formatNumber } from "@/lib/format";
import { admin } from "@/lib/server/gateway";
import type { Me } from "@/lib/types";

import { CreateKeyDialog } from "./_components/create-key-dialog";
import { KeysTable, KeysTableSkeleton } from "./_components/keys-table";

export default async function KeysPage() {
  const me = await admin<Me>("/me");
  const limits = me.limits;
  const atCap = limits !== null && me.active_keys >= limits.max_keys;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Keys"
        description={
          limits
            ? `${me.active_keys} of ${limits.max_keys} active keys · up to ${formatNumber(limits.max_rpm)} requests/min and ${formatNumber(limits.max_daily_tokens)} tokens/day per key (UTC).`
            : "Each key has its own requests-per-minute limit and daily token quota (UTC)."
        }
        actions={<CreateKeyDialog limits={limits} disabledReason={atCap ? "Key limit reached. Revoke a key to create another." : undefined} />}
      />
      <Suspense fallback={<KeysTableSkeleton />}>
        <KeysTable />
      </Suspense>
    </div>
  );
}
