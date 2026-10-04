import "server-only";

// Server-side gateway access. ADMIN_TOKEN never leaves the server.
export const GATEWAY_URL = (process.env.GATEWAY_URL ?? "http://localhost:8000").replace(/\/$/, "");
const ADMIN_TOKEN = process.env.ADMIN_TOKEN ?? "";
const TIMEOUT_MS = 10_000;

export function gatewayError(status: number, type: string, message: string): Response {
  return Response.json({ error: { type, message } }, { status });
}

export async function gatewayFetch(
  path: string,
  init: { method?: string; body?: string; contentType?: string | null; admin?: boolean; timeoutMs?: number } = {},
): Promise<Response> {
  const headers = new Headers();
  if (init.body !== undefined) headers.set("Content-Type", init.contentType ?? "application/json");
  if (init.admin) headers.set("Authorization", `Bearer ${ADMIN_TOKEN}`);

  return fetch(`${GATEWAY_URL}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body,
    cache: "no-store",
    signal: AbortSignal.timeout(init.timeoutMs ?? TIMEOUT_MS),
  });
}

export function isAdminTokenConfigured(): boolean {
  return ADMIN_TOKEN.length > 0;
}
