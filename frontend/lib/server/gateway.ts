import "server-only";

import { readFileSync } from "node:fs";

import { auth } from "@clerk/nextjs/server";

import { CLERK_ENABLED } from "@/lib/auth-config";

// Server-side gateway access for Server Components, Server Actions and Route Handlers.
// ADMIN_TOKEN never leaves the server. Admin calls are scoped to the signed-in Clerk user via
// X-Tollgate-User; the gateway trusts that header only together with ADMIN_TOKEN.
export const GATEWAY_URL = (process.env.GATEWAY_URL ?? "http://localhost:8000").replace(/\/$/, "");
let cachedToken: string | undefined;

/** ADMIN_TOKEN, or the token docker compose generates into ADMIN_TOKEN_FILE on first start. */
function adminToken(): string {
  if (cachedToken) return cachedToken;
  let token = process.env.ADMIN_TOKEN?.trim() ?? "";
  if (!token && process.env.ADMIN_TOKEN_FILE) {
    try {
      token = readFileSync(process.env.ADMIN_TOKEN_FILE, "utf8").trim();
    } catch {
      token = "";
    }
  }
  if (token) cachedToken = token;
  return token;
}
const TIMEOUT_MS = 15_000;

export class GatewayRequestError extends Error {
  constructor(
    readonly status: number,
    readonly type: string,
    message: string,
  ) {
    super(message);
    this.name = "GatewayRequestError";
  }
}

type FetchOptions = { method?: string; body?: unknown; admin?: boolean; userId?: string; timeoutMs?: number };

export async function gatewayFetch(path: string, options: FetchOptions = {}): Promise<Response> {
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.admin) headers.set("Authorization", `Bearer ${adminToken()}`);
  if (options.userId) headers.set("X-Tollgate-User", options.userId);

  return fetch(`${GATEWAY_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
    signal: AbortSignal.timeout(options.timeoutMs ?? TIMEOUT_MS),
  });
}

async function toError(res: Response): Promise<GatewayRequestError> {
  try {
    const body = (await res.json()) as { error?: { type?: string; message?: string } };
    return new GatewayRequestError(res.status, body.error?.type ?? "error", body.error?.message ?? res.statusText);
  } catch {
    return new GatewayRequestError(res.status, "error", res.statusText || `HTTP ${res.status}`);
  }
}

/** The signed-in Clerk user, or undefined in local mode (operator view). */
async function currentUserId(): Promise<string | undefined> {
  if (!CLERK_ENABLED) return undefined;
  const { userId, redirectToSignIn } = await auth();
  return userId ?? redirectToSignIn();
}

/** Typed call to the gateway's /admin API as the signed-in user. Throws GatewayRequestError on any failure. */
export async function admin<T>(path: string, options: Omit<FetchOptions, "admin" | "userId"> = {}): Promise<T> {
  if (!adminToken()) {
    throw new GatewayRequestError(500, "misconfigured", "ADMIN_TOKEN (or ADMIN_TOKEN_FILE) is not set for the dashboard.");
  }
  const userId = await currentUserId();
  let res: Response;
  try {
    res = await gatewayFetch(`/admin${path}`, { ...options, admin: true, userId });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    console.error(`[gateway] ${options.method ?? "GET"} /admin${path} failed:`, error);
    throw timedOut
      ? new GatewayRequestError(504, "gateway_timeout", `Gateway at ${GATEWAY_URL} did not respond in time.`)
      : new GatewayRequestError(502, "gateway_unreachable", `Cannot reach the gateway at ${GATEWAY_URL}.`);
  }
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}
