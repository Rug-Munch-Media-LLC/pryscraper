# @pryscraper/sdk

Typed TypeScript client for the Pry scraping API and MCP server.

```bash
npm install @pryscraper/sdk   # not yet published; use a path install today
```

> Not on npm yet. Install from the repo: `npm install /path/to/pryscraper/sdk/typescript`.

## Quickstart

```ts
import { PryClient } from "@pryscraper/sdk";

const pry = new PryClient({ apiKey: process.env.PRY_API_KEY!, baseUrl: "https://api.pryscraper.com" });
const page = await pry.scrape("https://example.com", { formats: ["markdown", "links"] });
console.log(page.markdown);
```

## Surface

`scrape` · `crawl` · `map` · `search` · `batch` · `extract` · `health`

Every method takes `RequestOptions` (`timeoutMs`, `signal`, `headers`).

## Auth

`Authorization: Bearer <api key>` — sent automatically. Anonymous calls are rate-limited per IP.

## Errors

| Class | When | Extras |
|---|---|---|
| `PryPaymentRequired` | 402 | `challenge`, `invoiceRequired`, `paymentId`, `accepts` |
| `PryRateLimitError` | 429 | `retryAfterSeconds` |
| `PryNetworkError` | transport/timeout | `cause` |
| `PryError` | any non-2xx | `status`, `code`, `requestId`, `details` |

x402: pass `pay` to settle a challenge automatically (one retry with `X-PAYMENT`), and `maxPriceUsd` to refuse expensive calls.

```ts
const pry = new PryClient({ apiKey, pay: async (challenge) => sign(challenge.accepts[0]), maxPriceUsd: 0.05 });
```

## MCP

```ts
import { PryMcpClient } from "@pryscraper/sdk";
const mcp = new PryMcpClient({ url: "https://api.pryscraper.com/mcp/", apiKey });
await mcp.initialize();
const tools = await mcp.listTools();          // 99 tools
await mcp.callTool("pry_scrape", { url: "https://example.com" });
```

For stdio clients (Claude Desktop, Cursor, Cline) use the server package instead:
`uvx pryscraper-mcp` with `PRY_API_KEY`. See `docs/mcp/CLIENTS.md`.

## Develop

```bash
npm install && npm test && npx tsc --noEmit
```
