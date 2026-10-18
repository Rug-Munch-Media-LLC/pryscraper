// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC

import { test } from "node:test";
import assert from "node:assert/strict";

import { PryClient, PryMcpClient, PryMcpError } from "../src/index.ts";
import { PryNetworkError, PryPaymentRequired, PryRateLimitError } from "../src/errors.ts";

type Handler = (url: string, init: RequestInit) => Promise<Response>;

/** Build a client whose transport is a scripted handler; records calls. */
function mockClient(handler: Handler, extra: Record<string, unknown> = {}) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init: init ?? {} });
    return handler(url, init ?? {});
  }) as unknown as typeof globalThis.fetch;
  const client = new PryClient({ baseUrl: "https://pry.test", fetch: fetchImpl, ...extra });
  return { client, calls };
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

test("scrape: happy path sends url + options and returns typed data", async () => {
  const { client, calls } = mockClient(async () =>
    json({
      success: true,
      data: {
        markdown: "# Hello",
        metadata: {
          url: "https://example.com",
          method: "direct",
          title: "Hello",
          description: "",
          markdown_quality: 0.9,
          formats: ["markdown"],
        },
      },
    }),
  );

  const res = await client.scrape("https://example.com", { formats: ["markdown"], timeout: 90 });
  assert.equal(res.data.markdown, "# Hello");
  assert.equal(res.data.metadata.method, "direct");
  const sent = JSON.parse(String(calls[0]?.init.body));
  assert.deepEqual(sent, { url: "https://example.com", formats: ["markdown"], timeout: 90 });
  assert.equal(calls[0]?.url, "https://pry.test/v1/scrape");
});

test("scrape: apiKey becomes a Bearer header", async () => {
  const { client, calls } = mockClient(
    async () => json({ success: true, data: { markdown: "", metadata: {} } }),
    { apiKey: "pry_test" },
  );
  await client.scrape("https://example.com");
  const headers = new Headers(calls[0]?.init.headers);
  assert.equal(headers.get("authorization"), "Bearer pry_test");
});

test("402: becomes a typed PryPaymentRequired carrying the challenge", async () => {
  const challenge = {
    x402Version: 1,
    accepts: [
      {
        scheme: "exact",
        network: "eip155:8453",
        maxAmountRequired: "1000",
        payToAddress: "0xTreasury",
        asset: "USDC",
        extra: { decimals: 6 },
      },
    ],
    invoice_required: true,
    payment_id: "pay_abc123",
    error: "payment required",
  };
  const { client } = mockClient(async () => json(challenge, 402));

  await assert.rejects(client.scrape("https://example.com"), (err: unknown) => {
    assert.ok(err instanceof PryPaymentRequired);
    assert.equal(err.status, 402);
    assert.equal(err.invoiceRequired, true);
    assert.equal(err.paymentId, "pay_abc123");
    assert.equal(err.accepts.length, 1);
    assert.equal(err.accepts[0]?.payToAddress, "0xTreasury");
    return true;
  });
});

test("402: a pay callback buys exactly one retry with PAYMENT-SIGNATURE", async () => {
  let seen = 0;
  const { client, calls } = mockClient(async (_url, init) => {
    seen += 1;
    if (seen === 1) {
      return json({ x402Version: 1, accepts: [], payment_id: "p1" }, 402);
    }
    const headers = new Headers(init.headers);
    assert.ok(headers.get("payment-signature"));
    return json({ success: true, data: { markdown: "paid", metadata: {} } });
  }, {
    pay: (challenge: { payment_id?: string }) => ({ payment_id: challenge.payment_id, tx_hash: "0x1" }),
  });

  const res = await client.scrape("https://example.com");
  assert.equal(res.data.markdown, "paid");
  assert.equal(calls.length, 2);
});

test("429: raises PryRateLimitError with Retry-After seconds", async () => {
  const { client } = mockClient(async () =>
    json({ title: "Too Many Requests", status: 429, detail: "slow down" }, 429, {
      "retry-after": "7",
    }),
  );

  await assert.rejects(client.scrape("https://example.com"), (err: unknown) => {
    assert.ok(err instanceof PryRateLimitError);
    assert.equal(err.retryAfterSeconds, 7);
    assert.equal(err.code, "too_many_requests");
    return true;
  });
});

test("network failure: raises PryNetworkError with status 0", async () => {
  const { client } = mockClient(async () => {
    throw new TypeError("fetch failed");
  });

  await assert.rejects(client.scrape("https://example.com"), (err: unknown) => {
    assert.ok(err instanceof PryNetworkError);
    assert.equal(err.status, 0);
    assert.equal(err.code, "network_error");
    return true;
  });
});

test("map: returns the canonical {url, links, count} contract", async () => {
  const { client } = mockClient(async () =>
    json({ url: "https://example.com", links: [{ url: "https://example.com/a" }], count: 1 }),
  );
  const res = await client.map("https://example.com", { limit: 10 });
  assert.equal(res.count, 1);
  assert.equal(res.links[0]?.url, "https://example.com/a");
});

test("mcp: callTool posts JSON-RPC and parses an SSE frame", async () => {
  const sse = (id: number, result: unknown) =>
    new Response(`event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id, result })}\n\n`, {
      status: 200,
      headers: { "content-type": "text/event-stream", "mcp-session-id": "sess-1" },
    });

  let seen = 0;
  const fetchImpl = (async (_input: string | URL | Request, init?: RequestInit) => {
    seen += 1;
    const body = JSON.parse(String(init?.body)) as { id: number; method: string };
    if (body.method === "initialize") {
      return sse(body.id, { protocolVersion: "2025-06-18", capabilities: {} });
    }
    assert.equal(new Headers(init?.headers).get("mcp-session-id"), "sess-1");
    return sse(body.id, { content: [{ type: "text", text: "# done" }] });
  }) as unknown as typeof globalThis.fetch;

  const mcp = new PryMcpClient({ url: "https://pry.test/mcp/", fetch: fetchImpl });
  const result = await mcp.scrape("https://example.com");
  assert.equal(result.content[0]?.text, "# done");
  assert.equal(seen, 2);
});

test("mcp: a JSON-RPC error becomes PryMcpError", async () => {
  const fetchImpl = (async (_i: string | URL | Request, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { id: number; method: string };
    if (body.method === "initialize") {
      return json({ jsonrpc: "2.0", id: body.id, result: { capabilities: {} } });
    }
    return json({
      jsonrpc: "2.0",
      id: body.id,
      error: { code: -32602, message: "url required" },
    });
  }) as unknown as typeof globalThis.fetch;

  const mcp = new PryMcpClient({ url: "https://pry.test/mcp/", fetch: fetchImpl });
  await assert.rejects(mcp.scrape(""), (err: unknown) => {
    assert.ok(err instanceof PryMcpError);
    assert.equal(err.code, -32602);
    return true;
  });
});
