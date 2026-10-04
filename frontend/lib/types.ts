// Shapes returned by the gateway (and the dashboard's own route handlers).
export type GatewayHealth = { status: "ok" | "degraded" | "offline"; redis: boolean; db: boolean };
