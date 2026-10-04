// Shapes returned by the gateway (mirrors backend/app/schemas.py).

export type GatewayHealth = { status: "ok" | "degraded" | "offline"; redis: boolean; db: boolean };

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  rpm: number;
  daily_token_quota: number;
  created_at: string;
  revoked_at: string | null;
  tokens_today: number;
};

export type CreatedApiKey = ApiKey & { key: string };

export type KeyUsage = {
  key_id: string | null;
  name: string | null;
  prefix: string | null;
  requests: number;
  tokens: number;
  errors: number;
};

export type ModelUsage = { model: string | null; requests: number; tokens: number };

export type Stats = {
  window_hours: number;
  requests: number;
  errors: number;
  error_rate: number;
  cache_hits: number;
  cache_hit_rate: number;
  fallbacks: number;
  in_tokens: number;
  out_tokens: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  by_key: KeyUsage[];
  by_model: ModelUsage[];
};

export type RequestLog = {
  id: number;
  ts: string;
  key_id: string | null;
  key_name: string | null;
  key_prefix: string | null;
  alias: string;
  model_used: string | null;
  in_tokens: number;
  out_tokens: number;
  latency_ms: number;
  status: number;
  cache_hit: boolean;
  fallback_used: boolean;
};

export type LogPage = { items: RequestLog[]; next_cursor: number | null };

export type AliasInfo = { id: string; chain: string[]; terse: boolean };
