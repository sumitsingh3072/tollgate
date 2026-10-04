// Helpers for reading Next.js searchParams safely.
export type SearchParams = Record<string, string | string[] | undefined>;

export function param(params: SearchParams, name: string): string | undefined {
  const value = params[name];
  return Array.isArray(value) ? value[0] : value || undefined;
}

export function intParam(params: SearchParams, name: string, allowed?: readonly number[]): number | undefined {
  const raw = param(params, name);
  const value = raw === undefined ? NaN : Number(raw);
  if (!Number.isInteger(value)) return undefined;
  return allowed && !allowed.includes(value) ? undefined : value;
}
