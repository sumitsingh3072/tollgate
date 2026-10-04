# Tollgate dashboard

Next.js 16 + shadcn/ui (base-nova) + Tailwind v4. Linear-inspired light/dark theme.

```bash
cp .env.example .env.local
pnpm dev        # http://localhost:3000
pnpm lint && pnpm build
```

Admin calls go through `app/api/admin/[...path]` so `ADMIN_TOKEN` never reaches the browser.
