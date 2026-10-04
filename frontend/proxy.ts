import { clerkMiddleware } from "@clerk/nextjs/server";
import { type NextRequest, NextResponse } from "next/server";

import { CLERK_ENABLED } from "@/lib/auth-config";

// Hosts the sign-in-less local dashboard answers on. Anything else (a LAN address, a public domain,
// or a DNS-rebinding attacker's name pointing at 127.0.0.1) is refused. Extra trusted names can be
// listed in DASHBOARD_TRUSTED_HOSTS, comma-separated, at your own risk.
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function trustedHosts(): Set<string> {
  const extra = (process.env.DASHBOARD_TRUSTED_HOSTS ?? "").split(",").map((h) => h.trim().toLowerCase());
  return new Set([...LOCAL_HOSTS, ...extra.filter(Boolean)]);
}

function refuse(status: number, message: string): NextResponse {
  return new NextResponse(message, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

function localMode(req: NextRequest): NextResponse {
  // Clerk keys present at runtime but not compiled in: refuse instead of serving operator access.
  if (process.env.CLERK_SECRET_KEY) {
    return refuse(
      503,
      "Clerk keys were added after this dashboard was built. Rebuild it: docker compose up -d --build",
    );
  }
  const host = (req.headers.get("host") ?? "").replace(/:\d+$/, "").toLowerCase();
  if (!trustedHosts().has(host)) {
    return refuse(403, "This dashboard runs without sign-in, so it only answers on localhost. Enable Clerk to host it.");
  }
  return NextResponse.next();
}

// With Clerk: attach the session to every request. Access checks live next to the data:
// app/(app)/layout.tsx (auth.protect) and lib/server/gateway.ts (every admin call needs a user).
export default CLERK_ENABLED ? clerkMiddleware() : localMode;

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest|txt)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
