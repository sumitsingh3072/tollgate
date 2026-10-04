// Browser-side config. Admin calls happen server-side (Server Components / Server Actions).
export const GATEWAY_URL = (process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000").replace(/\/$/, "");
