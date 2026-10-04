"use client";

import { useCallback, useRef, useState } from "react";

import { GATEWAY_URL } from "@/lib/api";
import { readSSE } from "@/lib/sse";

export type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

export type ResponseMeta = {
  status: number;
  model: string | null;
  cache: string | null;
  fallback: string | null;
  requestId: string | null;
  requestsRemaining: string | null;
  tokensRemaining: string | null;
  firstTokenMs: number | null;
  totalMs: number;
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null;
};

export type ChatSettings = { apiKey: string; model: string; temperature: number; stream: boolean; system: string };

type Chunk = {
  choices?: { delta?: { content?: string } }[];
  usage?: ResponseMeta["usage"];
};

function metaFromHeaders(res: Response, started: number): ResponseMeta {
  const h = res.headers;
  return {
    status: res.status,
    model: h.get("x-tollgate-model"),
    cache: h.get("x-tollgate-cache"),
    fallback: h.get("x-tollgate-fallback"),
    requestId: h.get("x-request-id"),
    requestsRemaining: h.get("x-ratelimit-remaining-requests"),
    tokensRemaining: h.get("x-ratelimit-remaining-tokens"),
    firstTokenMs: null,
    totalMs: Math.round(performance.now() - started),
    usage: null,
  };
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    return body.error?.message ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

/** Calls the gateway's /v1/chat/completions directly from the browser with a pasted Tollgate key. */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [meta, setMeta] = useState<ResponseMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const appendToReply = useCallback((text: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      return [...prev.slice(0, -1), { ...last, content: last.content + text }];
    });
  }, []);

  const send = useCallback(
    async (prompt: string, settings: ChatSettings) => {
      const history: ChatMessage[] = [...messages, { role: "user", content: prompt }];
      setMessages([...history, { role: "assistant", content: "" }]);
      setError(null);
      setMeta(null);
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;
      const started = performance.now();
      const payloadMessages = settings.system ? [{ role: "system", content: settings.system }, ...history] : history;

      try {
        const res = await fetch(`${GATEWAY_URL}/v1/chat/completions`, {
          method: "POST",
          headers: { Authorization: `Bearer ${settings.apiKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            model: settings.model,
            messages: payloadMessages,
            temperature: settings.temperature,
            stream: settings.stream,
          }),
          signal: controller.signal,
        });
        const base = metaFromHeaders(res, started);
        if (!res.ok) {
          setMeta(base);
          setMessages(history);
          setError(await errorMessage(res));
          return;
        }

        if (settings.stream && res.body) {
          let firstTokenMs: number | null = null;
          let usage: ResponseMeta["usage"] = null;
          for await (const chunk of readSSE<Chunk>(res.body)) {
            const text = chunk.choices?.[0]?.delta?.content;
            if (text) {
              firstTokenMs ??= Math.round(performance.now() - started);
              appendToReply(text);
            }
            usage = chunk.usage ?? usage;
          }
          setMeta({ ...base, firstTokenMs, usage, totalMs: Math.round(performance.now() - started) });
        } else {
          const body = (await res.json()) as {
            choices?: { message?: { content?: string } }[];
            usage?: ResponseMeta["usage"];
          };
          appendToReply(body.choices?.[0]?.message?.content ?? "");
          setMeta({ ...base, usage: body.usage ?? null, totalMs: Math.round(performance.now() - started) });
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setMessages(history);
        setError(
          err instanceof TypeError
            ? `Cannot reach the gateway at ${GATEWAY_URL}. Is it running, and is this origin in CORS_ORIGINS?`
            : String(err),
        );
      } finally {
        abortRef.current = null;
        setBusy(false);
      }
    },
    [messages, appendToReply],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setMeta(null);
    setError(null);
  }, []);

  return { messages, meta, error, busy, send, stop, reset };
}
