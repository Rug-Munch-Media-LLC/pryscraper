# Coverage, Vision & Crypto APIs

Three surfaces that are easy to miss in the REST reference: the free coverage
catalog, the paid vision endpoint, and the crypto data routes.

## Coverage catalog (free)

`/v1/coverage*` is mounted at the API root and is **not** x402-gated. Use it to
pick a method before spending a paid call.

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/v1/coverage` | Full site catalog: every site, method and delivery schema |
| `GET` | `/v1/coverage/{site_id}` | One site: method, confidence, delivery schema |
| `GET` | `/v1/coverage/recommend?url=…` | Recommended method for a URL or domain |

```bash
curl -s http://localhost:8005/v1/coverage/recommend?url=https://example.com
```

The coverage router declares no prefix, so these paths are matched at the API
root and are exempt from payment classification — a paid prefix such as
`/v1/crypto/*` does not accidentally gate them.

## Vision (paid)

| Method | Path | Price |
|--------|------|------:|
| `POST` | `/v1/vision` | $0.01 (`llm_call`) |
| `GET` | `/v1/vision/models` | free |

`POST /v1/vision` analyses an image with an LLM and is priced as an LLM call.
Listing the available models is free — only the analysis is charged.

```bash
curl -i -s -X POST http://localhost:8005/v1/vision \
  -H 'Content-Type: application/json' \
  -d '{"image_url":"https://example.com/chart.png","prompt":"Describe the trend"}'
# HTTP/1.1 402 Payment Required (unpaid)
```

Pay the quoted amount, then retry with `PAYMENT-SIGNATURE`.

## Crypto data

Three routes, all GET, all paid at $0.002–$0.005:

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/v1/crypto/token-launches` | New tokens, pairs, or trending tokens |
| `GET` | `/v1/crypto/cex-listings` | Recent CEX listing and delisting signals |
| `GET` | `/v1/crypto/token-security/{chain}/{address}` | Token security scan for one chain/address |

`{chain}` is the chain slug (`base`, `ethereum`, `bsc`, …) and `{address}` is the
token contract. These paths match the `/v1/crypto/*` paid prefix; the 402
challenge quotes the exact operation price.

## See also

- [x402 pricing](../x402/pricing) — the live price table.
- [Scrape API](scrape) — the core paid endpoint.
