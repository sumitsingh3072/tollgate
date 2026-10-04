import { clerkMiddleware } from "@clerk/nextjs/server";

// Attaches the Clerk session to every request. Access checks live next to the data:
// app/(app)/layout.tsx (auth.protect) and lib/server/gateway.ts (every admin call needs a user).
export default clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest|txt)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
