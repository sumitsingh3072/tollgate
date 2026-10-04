import { gatewayFetch } from "@/lib/server/gateway";
import type { GatewayHealth } from "@/lib/types";

const OFFLINE: GatewayHealth = { status: "offline", redis: false, db: false };

export async function GET(): Promise<Response> {
  try {
    const res = await gatewayFetch("/health", { timeoutMs: 5_000 });
    if (!res.ok) return Response.json(OFFLINE);
    return Response.json((await res.json()) as GatewayHealth);
  } catch {
    return Response.json(OFFLINE);
  }
}
