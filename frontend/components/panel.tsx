import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Panel({
  title,
  description,
  children,
  className,
  flush,
  actions,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  /** No inner padding (tables). */
  flush?: boolean;
  actions?: ReactNode;
}) {
  return (
    <section className={cn("rounded-lg border bg-card", className)}>
      <header className="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="font-medium">{title}</h2>
          {description && <p className="text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}
