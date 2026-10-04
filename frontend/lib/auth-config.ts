// Accounts are optional. Without Clerk keys the app runs in local mode: no sign-in, and the dashboard
// acts as the single operator (bind it to localhost, which docker compose does by default).
// NEXT_PUBLIC_* is inlined at build time, so this is a constant in both server and client bundles.
export const CLERK_ENABLED = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

/** Where "Get started" buttons go. */
export const START_HREF = CLERK_ENABLED ? "/sign-up" : "/dashboard";
