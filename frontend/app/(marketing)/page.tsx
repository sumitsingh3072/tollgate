import {
  ActivityIcon,
  ArrowRightIcon,
  DatabaseZapIcon,
  GaugeIcon,
  KeyRoundIcon,
  RadioIcon,
  RouteIcon,
  ScissorsIcon,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { CodeTabs } from "@/components/marketing/code-tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GATEWAY_URL } from "@/lib/api";
import { START_HREF } from "@/lib/auth-config";

const FEATURES = [
  {
    icon: KeyRoundIcon,
    title: "API keys",
    body: "Issue keys per app or teammate. Only a SHA-256 hash is stored; revoking takes effect immediately.",
  },
  {
    icon: GaugeIcon,
    title: "Rate limits and quotas",
    body: "Requests per minute and a daily token budget per key, enforced in Redis in a single round trip.",
  },
  {
    icon: DatabaseZapIcon,
    title: "Exact-match cache",
    body: "Deterministic requests are answered from cache in milliseconds and never touch the model.",
  },
  {
    icon: RouteIcon,
    title: "Fallback and circuit breaker",
    body: "If a model errors, times out or is overloaded, the next one in the chain answers. Failing models are skipped.",
  },
  {
    icon: RadioIcon,
    title: "Streaming passthrough",
    body: "Server-sent events are relayed chunk by chunk, with token usage counted even when clients disconnect.",
  },
  {
    icon: ScissorsIcon,
    title: "Terse mode",
    body: "A *-terse alias asks the model for the shortest correct answer. In testing it cut output tokens by 85%.",
  },
  {
    icon: ActivityIcon,
    title: "Logs and analytics",
    body: "Every request logged without slowing it down: latency percentiles, cache hit rate, errors and usage by key.",
  },
];

const STEPS = [
  { title: "Create a key", body: "Open the dashboard and create a key with its own rate limit and daily token quota." },
  { title: "Change one line", body: "Point any OpenAI SDK, Open WebUI or n8n at the gateway with base_url." },
  { title: "Watch it work", body: "See traffic, cache hits, fallbacks and latency in the dashboard as they happen." },
];

const NUMBERS = [
  { value: "~4 ms", label: "cache hit response" },
  { value: "1 line", label: "to switch: base_url" },
  { value: "85%", label: "fewer output tokens with terse mode" },
  { value: "0", label: "database calls on the request path" },
];

function Section({ id, eyebrow, title, children }: { id?: string; eyebrow: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 md:px-6">
      <p className="text-sm font-medium text-primary">{eyebrow}</p>
      <h2 className="mt-2 max-w-2xl text-3xl font-semibold tracking-tight text-balance">{title}</h2>
      <div className="mt-10">{children}</div>
    </section>
  );
}

export default function LandingPage() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 -top-40 h-[36rem] bg-[radial-gradient(ellipse_at_top,color-mix(in_oklch,var(--primary)_18%,transparent),transparent_65%)]"
        />
        <div className="relative mx-auto max-w-6xl px-4 pt-20 pb-12 text-center md:px-6 md:pt-28">
          <Badge variant="outline" className="mb-6 gap-1.5 rounded-full px-3 py-1 text-xs">
            <span className="size-1.5 rounded-full bg-success" />
            OpenAI-compatible · local with Ollama or hosted with Gemini
          </Badge>
          <h1 className="mx-auto max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl md:text-6xl">
            The gateway between your apps and your models
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-base text-muted-foreground text-pretty md:text-lg">
            API keys, rate limits, token quotas, caching, model fallback and analytics in one place. Your code changes
            exactly one line: <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em]">base_url</code>.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" render={<Link href={START_HREF} />}>
              Get started
              <ArrowRightIcon />
            </Button>
            <Button size="lg" variant="outline" render={<a href="#quickstart" />}>
              See the quickstart
            </Button>
          </div>
        </div>

        {/* Product shot */}
        <div className="relative mx-auto max-w-6xl px-4 pb-8 md:px-6">
          <div className="rounded-xl border bg-card p-1.5 shadow-2xl shadow-primary/10 ring-1 ring-foreground/5">
            <Image
              src="/landing/dashboard-light.jpg"
              alt="Tollgate dashboard overview with request, token and latency charts"
              width={2160}
              height={1350}
              priority
              className="rounded-lg dark:hidden"
            />
            <Image
              src="/landing/dashboard-dark.jpg"
              alt="Tollgate dashboard overview with request, token and latency charts"
              width={2160}
              height={1350}
              priority
              className="hidden rounded-lg dark:block"
            />
          </div>
        </div>
      </section>

      {/* Numbers */}
      <section className="border-y bg-muted/30">
        <dl className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-10 md:grid-cols-4 md:px-6">
          {NUMBERS.map((n) => (
            <div key={n.label}>
              <dt className="text-xs text-muted-foreground">{n.label}</dt>
              <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{n.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <Section id="features" eyebrow="Features" title="Everything between a request and a model, handled">
        <div className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="bg-card p-6 transition-colors hover:bg-muted/40">
              <span className="flex size-9 items-center justify-center rounded-lg border bg-background text-primary">
                <Icon className="size-4" />
              </span>
              <h3 className="mt-4 font-medium">{title}</h3>
              <p className="mt-1.5 text-muted-foreground">{body}</p>
            </div>
          ))}
          <div className="flex flex-col justify-center gap-3 bg-card p-6">
            <p className="font-medium">And it&apos;s yours</p>
            <p className="text-muted-foreground">
              <code className="font-mono text-foreground">docker compose up</code> runs everything locally: models,
              database and dashboard. Your keys, your logs, your models.
            </p>
          </div>
        </div>
      </Section>

      <Section id="how-it-works" eyebrow="How it works" title="From docker compose up to first request in minutes">
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <li key={step.title} className="rounded-xl border bg-card p-6">
              <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary tabular-nums">
                {i + 1}
              </span>
              <h3 className="mt-4 font-medium">{step.title}</h3>
              <p className="mt-1.5 text-muted-foreground">{step.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="quickstart" eyebrow="Quickstart" title="Keep your SDK. Change the base URL.">
        <div className="grid items-start gap-8 lg:grid-cols-[1fr_1.4fr]">
          <div className="space-y-4 text-muted-foreground">
            <p>
              Tollgate speaks the OpenAI API, so existing clients work unchanged. Pick a model alias:{" "}
              <code className="font-mono text-foreground">fast</code>, <code className="font-mono text-foreground">smart</code>{" "}
              (with automatic fallback) or <code className="font-mono text-foreground">smart-terse</code>.
            </p>
            <p>
              Every response carries headers telling you which model answered, whether it came from cache and whether a
              fallback kicked in.
            </p>
            <Button variant="outline" render={<a href={`${GATEWAY_URL}/docs`} />}>
              API reference
            </Button>
          </div>
          <CodeTabs gatewayUrl={GATEWAY_URL} />
        </div>
      </Section>

      {/* Final CTA */}
      <section className="mx-auto max-w-6xl px-4 pb-24 md:px-6">
        <div className="relative overflow-hidden rounded-2xl border bg-card px-6 py-14 text-center">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,color-mix(in_oklch,var(--primary)_14%,transparent),transparent_70%)]"
          />
          <h2 className="relative text-3xl font-semibold tracking-tight">Put a gateway in front of your models</h2>
          <p className="relative mx-auto mt-3 max-w-xl text-muted-foreground">
            Create a key, change one line, and see every request in the dashboard.
          </p>
          <Button size="lg" className="relative mt-8" render={<Link href={START_HREF} />}>
            Get started
            <ArrowRightIcon />
          </Button>
        </div>
      </section>
    </>
  );
}
