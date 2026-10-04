import type { NextRequest } from "next/server";

// Server-side proxy to the gateway's /admin API. Adds ADMIN_TOKEN so it never reaches the browser.
const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://localhost:8000";
const ADMIN_TOKEN = process.env.ADMIN_TOKEN ?? "";

async function forward(req: NextRequest, ctx: RouteContext<"/api/admin/[...path]">) {
  const { path } = await ctx.params;
  const url = `${GATEWAY_URL}/admin/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const hasBody = req.method !== "GET" && req.method !== "DELETE";
  try {
    const upstream = await fetch(url, {
      method: req.method,
      headers: {
        Authorization: `Bearer ${ADMIN_TOKEN}`,
        "Content-Type": req.headers.get("content-type") ?? "application/json",
      },
      body: hasBody ? await req.text() : undefined,
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json(
      { error: { type: "gateway_unreachable", message: `Cannot reach ${GATEWAY_URL}` } },
      { status: 502 },
    );
  }
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
