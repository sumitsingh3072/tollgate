"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { Switch } from "@/components/ui/switch";

/** Re-renders the server page every few seconds while switched on (for live views). */
export function AutoRefresh({ seconds = 5 }: { seconds?: number }) {
  const router = useRouter();
  const [on, setOn] = useState(true);
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => startTransition(() => router.refresh()), seconds * 1000);
    return () => clearInterval(id);
  }, [on, seconds, router]);

  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      <Switch checked={on} onCheckedChange={setOn} aria-label="Live refresh" />
      Live ({seconds}s)
    </label>
  );
}
