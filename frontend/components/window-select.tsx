"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export const WINDOWS = [
  { value: "24", label: "Last 24 hours" },
  { value: "168", label: "Last 7 days" },
  { value: "720", label: "Last 30 days" },
] as const;

export function WindowSelect({ hours }: { hours: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();

  return (
    <Select
      items={WINDOWS}
      value={String(hours)}
      onValueChange={(value) => {
        const params = new URLSearchParams(searchParams);
        params.set("hours", String(value));
        startTransition(() => router.replace(`${pathname}?${params}`));
      }}
    >
      <SelectTrigger size="sm" aria-label="Time window" data-pending={pending || undefined} className="data-pending:opacity-60">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {WINDOWS.map((w) => (
          <SelectItem key={w.value} value={w.value}>
            {w.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
