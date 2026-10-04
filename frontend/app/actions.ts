"use server";

import { refresh } from "next/cache";

import { admin, GatewayRequestError } from "@/lib/server/gateway";
import type { ApiKey, CreatedApiKey } from "@/lib/types";

export type ActionResult<T> = { ok: true; data: T } | { ok: false; error: string };

async function run<T>(fn: () => Promise<T>): Promise<ActionResult<T>> {
  try {
    const data = await fn();
    refresh();
    return { ok: true, data };
  } catch (error) {
    if (error instanceof GatewayRequestError) return { ok: false, error: error.message };
    console.error("[action] unexpected error:", error);
    return { ok: false, error: "Something went wrong. Check the dashboard server logs." };
  }
}

export type CreateKeyInput = { name: string; rpm: number; daily_token_quota: number };

export async function createKey(input: CreateKeyInput): Promise<ActionResult<CreatedApiKey>> {
  return run(() => admin<CreatedApiKey>("/keys", { method: "POST", body: input }));
}

export async function revokeKey(id: string): Promise<ActionResult<ApiKey>> {
  return run(() => admin<ApiKey>(`/keys/${encodeURIComponent(id)}`, { method: "DELETE" }));
}
