"use client";

import { useEffect, useState } from "react";

import { SidebarMenuButton } from "@/components/ui/sidebar";
import type { GatewayHealth } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_MS = 30_000;

const LABEL: Record<GatewayHealth["status"], string> = {
  ok: "Gateway online",
  degraded: "Gateway degraded",
  offline: "Gateway offline",
};

const DOT: Record<GatewayHealth["status"], string> = {
  ok: "bg-success",
  degraded: "bg-warning",
  offline: "bg-destructive",
};

export function GatewayStatus() {
  const [health, setHealth] = useState<GatewayHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        const data = (await res.json()) as GatewayHealth;
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth({ status: "offline", redis: false, db: false });
      }
    };
    void load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const label = health ? LABEL[health.status] : "Checking gateway…";
  const detail = health ? `Redis ${health.redis ? "up" : "down"} · DB ${health.db ? "up" : "down"}` : undefined;

  return (
    <SidebarMenuButton tooltip={detail ? `${label} — ${detail}` : label} className="cursor-default" aria-live="polite">
      <span className="flex size-4 items-center justify-center">
        <span className={cn("size-2 rounded-full", health ? DOT[health.status] : "animate-pulse bg-muted-foreground")} />
      </span>
      <span className="flex flex-col leading-tight">
        <span>{label}</span>
        {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
      </span>
    </SidebarMenuButton>
  );
}
