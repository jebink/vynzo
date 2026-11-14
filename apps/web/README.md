# @vynzo/web

The VYNZO website: Next.js (App Router).

```bash
pnpm --filter @vynzo/web dev     # http://localhost:3000 (API expected at NEXT_PUBLIC_API_BASE_URL)
```

| Path | Contents |
|---|---|
| `src/app/(public)` | Public, SEO-indexed pages (home, stock directory) |
| `src/app/(auth)` | Sign-in/up (Phase 2) |
| `src/app/(dashboard)` | Signed-in research app: dashboard, markets, `stocks/[symbol]`, … |
| `src/features/*` | Feature modules (components + hooks + API calls per feature) |
| `src/components`, `src/hooks`, `src/lib` | Shared, feature-agnostic code |
| `src/styles` | Global styles (Tailwind) |
