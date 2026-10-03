# Stockcast

AI demand forecasting and raw-material planning for ecommerce brands — Shopify, Amazon, eBay, WooCommerce and custom stores.

## One-command setup

```bash
make dev
```

Then open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs

Requires Docker. For running tests and lint outside Docker: Node 22 + pnpm 9 (`corepack enable`), Python 3.12 + [`uv`](https://docs.astral.sh/uv/), then `make install && make test`.

See `CLAUDE.md` for the stack, layout and coding rules.
