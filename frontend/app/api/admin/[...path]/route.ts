import type { NextRequest } from "next/server";

import { gatewayError, gatewayFetch, GATEWAY_URL, isAdminTokenConfigured } from "@/lib/server/gateway";

// Server-side proxy to the gateway's /admin API. Adds ADMIN_TOKEN so it never reaches the browser.
const PASSTHROUGH_HEADERS = ["content-type", "x-request-id"];

async function forward(req: NextRequest, ctx: RouteContext<"/api/admin/[...path]">): Promise<Response> {
  if (!isAdminTokenConfigured()) {
    return gatewayError(500, "misconfigured", "ADMIN_TOKEN is not set for the dashboard server");
  }
  const { path } = await ctx.params;
  const target = `/admin/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const hasBody = req.method === "POST";

  try {
    const upstream = await gatewayFetch(target, {
      method: req.method,
      body: hasBody ? await req.text() : undefined,
      contentType: req.headers.get("content-type"),
      admin: true,
    });
    const headers = new Headers();
    for (const name of PASSTHROUGH_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    console.error(`[admin-proxy] ${req.method} ${target} failed:`, error);
    return timedOut
      ? gatewayError(504, "gateway_timeout", `Gateway at ${GATEWAY_URL} did not respond in time`)
      : gatewayError(502, "gateway_unreachable", `Cannot reach gateway at ${GATEWAY_URL}`);
  }
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
