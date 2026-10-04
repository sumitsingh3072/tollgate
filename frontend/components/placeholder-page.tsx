import { PageHeader } from "@/components/page-header";
import type { NavItem } from "@/lib/nav";

export function PlaceholderPage({ item, phase }: { item: NavItem; phase: number }) {
  const Icon = item.icon;
  return (
    <div className="space-y-6">
      <PageHeader title={item.label} description={item.description} />
      <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-20 text-center">
        <span className="flex size-10 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
          <Icon className="size-5" />
        </span>
        <div className="space-y-1">
          <p className="font-medium">Arrives in Phase {phase}</p>
          <p className="text-muted-foreground">Tracked in docs/phase.md.</p>
        </div>
      </div>
    </div>
  );
}
