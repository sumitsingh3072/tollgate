"use client";

import { ArrowUpIcon, EraserIcon, FlaskConicalIcon, SquareIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSessionStorage } from "@/hooks/use-session-storage";
import { formatLatency, formatNumber } from "@/lib/format";
import type { AliasInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

import { type ChatMessage, type ResponseMeta, useChat } from "./use-chat";

const TEMPERATURES = [
  { value: "0", label: "0 · deterministic, cacheable" },
  { value: "0.7", label: "0.7 · balanced" },
  { value: "1", label: "1 · creative" },
];

function MetaRow({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("truncate text-right tabular-nums", mono && "font-mono text-xs")}>{value ?? "—"}</dd>
    </div>
  );
}

function ResponsePanel({ meta }: { meta: ResponseMeta | null }) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="mb-2 font-medium">Last response</h2>
      {meta ? (
        <dl className="divide-y text-[13px]">
          <MetaRow label="Status" value={meta.status} />
          <MetaRow label="Model" value={meta.model} mono />
          <MetaRow label="Cache" value={meta.cache} />
          <MetaRow label="Fallback" value={meta.fallback} />
          <MetaRow label="First token" value={meta.firstTokenMs === null ? null : formatLatency(meta.firstTokenMs)} />
          <MetaRow label="Total time" value={formatLatency(meta.totalMs)} />
          <MetaRow
            label="Tokens"
            value={meta.usage ? `${formatNumber(meta.usage.prompt_tokens)} in · ${formatNumber(meta.usage.completion_tokens)} out` : null}
          />
          <MetaRow label="Requests left" value={meta.requestsRemaining} />
          <MetaRow label="Tokens left today" value={meta.tokensRemaining && formatNumber(Number(meta.tokensRemaining))} />
          <MetaRow label="Request ID" value={meta.requestId} mono />
        </dl>
      ) : (
        <p className="text-muted-foreground">Gateway headers (model, cache, fallback, limits) show up here.</p>
      )}
    </section>
  );
}

function Message({ message, streaming }: { message: ChatMessage; streaming: boolean }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser && "justify-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 whitespace-pre-wrap",
          isUser ? "bg-primary text-primary-foreground" : "border bg-card",
        )}
      >
        {message.content || (streaming && <span className="inline-block h-4 w-1.5 animate-pulse bg-muted-foreground align-middle" />)}
      </div>
    </div>
  );
}

export function Playground({ aliases }: { aliases: AliasInfo[] }) {
  const [apiKey, setApiKey] = useSessionStorage("tollgate-playground-key");
  const [model, setModel] = useState(aliases[0]?.id ?? "fast");
  const [temperature, setTemperature] = useState("0.7");
  const [stream, setStream] = useState(true);
  const [system, setSystem] = useState("");
  const [prompt, setPrompt] = useState("");
  const { messages, meta, error, busy, send, stop, reset } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const selected = aliases.find((a) => a.id === model);
  const canSend = Boolean(apiKey.trim() && prompt.trim()) && !busy;

  function submit() {
    if (!canSend) return;
    void send(prompt.trim(), { apiKey: apiKey.trim(), model, temperature: Number(temperature), stream, system: system.trim() });
    setPrompt("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Playground"
        description="Chat through the gateway with a Tollgate key, exactly as an app would."
        actions={
          <Button variant="outline" size="sm" onClick={reset} disabled={messages.length === 0 && !error}>
            <EraserIcon />
            Clear
          </Button>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
        <section className="flex min-h-[28rem] flex-col rounded-lg border bg-card/40">
          <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
            {messages.length === 0 ? (
              <Empty className="h-full">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <FlaskConicalIcon />
                  </EmptyMedia>
                  <EmptyTitle>Send a message</EmptyTitle>
                  <EmptyDescription>
                    {apiKey ? (
                      <>Try the same prompt on smart and smart-terse, or demo-failover to watch a fallback.</>
                    ) : (
                      <>
                        Paste a key in the settings panel. No key yet? <Link href="/dashboard/keys">Create one</Link>.
                      </>
                    )}
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              messages.map((m, i) => (
                <Message key={i} message={m} streaming={busy && i === messages.length - 1} />
              ))
            )}
            {error && (
              <p role="alert" className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-destructive">
                <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" />
                {error}
              </p>
            )}
            <div ref={bottomRef} />
          </div>
          <div className="border-t p-3">
            <div className="flex items-end gap-2">
              <Textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={apiKey ? "Message… (Enter to send, Shift+Enter for a new line)" : "Paste a key first"}
                aria-label="Message"
                rows={2}
                className="max-h-48 min-h-10 resize-none"
              />
              {busy ? (
                <Button size="icon" variant="outline" onClick={stop} aria-label="Stop">
                  <SquareIcon />
                </Button>
              ) : (
                <Button size="icon" onClick={submit} disabled={!canSend} aria-label="Send">
                  <ArrowUpIcon />
                </Button>
              )}
            </div>
          </div>
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg border bg-card p-4">
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="pg-key">API key</FieldLabel>
                <Input
                  id="pg-key"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="tg_live_…"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="font-mono text-xs"
                />
                <FieldDescription>Kept in this tab only.</FieldDescription>
              </Field>
              <Field>
                <FieldLabel>Model alias</FieldLabel>
                <Select items={aliases.map((a) => ({ value: a.id, label: a.id }))} value={model} onValueChange={(v) => v && setModel(String(v))}>
                  <SelectTrigger className="w-full" aria-label="Model alias">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {aliases.map((a) => (
                      <SelectItem key={a.id} value={a.id}>
                        {a.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selected && (
                  <FieldDescription className="font-mono text-xs">
                    {selected.chain.join(" → ")}
                    {selected.terse && " · terse"}
                  </FieldDescription>
                )}
              </Field>
              <Field>
                <FieldLabel>Temperature</FieldLabel>
                <Select items={TEMPERATURES} value={temperature} onValueChange={(v) => v && setTemperature(String(v))}>
                  <SelectTrigger className="w-full" aria-label="Temperature">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TEMPERATURES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field orientation="horizontal">
                <FieldLabel htmlFor="pg-stream">Stream</FieldLabel>
                <Switch id="pg-stream" checked={stream} onCheckedChange={setStream} />
              </Field>
              <Field>
                <FieldLabel htmlFor="pg-system">System prompt</FieldLabel>
                <Textarea
                  id="pg-system"
                  value={system}
                  onChange={(e) => setSystem(e.target.value)}
                  placeholder="Optional"
                  rows={3}
                />
              </Field>
            </FieldGroup>
          </section>
          <ResponsePanel meta={meta} />
        </aside>
      </div>
    </div>
  );
}
