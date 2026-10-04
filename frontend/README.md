# Tollgate dashboard

Next.js 16 + shadcn/ui (base-nova) + Tailwind v4. Linear-inspired light/dark theme.

```bash
cp .env.example .env.local
pnpm dev        # http://localhost:3000
pnpm lint && pnpm build
```

Admin data is read in Server Components and changed through Server Actions (`app/actions.ts`),
so `ADMIN_TOKEN` never reaches the browser. The Playground calls the gateway's `/v1` directly
with a pasted Tollgate key.
