import "server-only";

// Server-side gateway access for Server Components, Server Actions and Route Handlers.
// ADMIN_TOKEN never leaves the server.
export const GATEWAY_URL = (process.env.GATEWAY_URL ?? "http://localhost:8000").replace(/\/$/, "");
const ADMIN_TOKEN = process.env.ADMIN_TOKEN ?? "";
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

type FetchOptions = { method?: string; body?: unknown; admin?: boolean; timeoutMs?: number };

export async function gatewayFetch(path: string, options: FetchOptions = {}): Promise<Response> {
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.admin) headers.set("Authorization", `Bearer ${ADMIN_TOKEN}`);

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

/** Typed call to the gateway's /admin API. Throws GatewayRequestError on any failure. */
export async function admin<T>(path: string, options: Omit<FetchOptions, "admin"> = {}): Promise<T> {
  if (!ADMIN_TOKEN) {
    throw new GatewayRequestError(500, "misconfigured", "ADMIN_TOKEN is not set for the dashboard server.");
  }
  let res: Response;
  try {
    res = await gatewayFetch(`/admin${path}`, { ...options, admin: true });
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
