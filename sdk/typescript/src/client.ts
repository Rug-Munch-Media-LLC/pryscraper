// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
//
// `PryClient` — typed client for the Pry scraping API.
// Reference implementation: `src/pry/api/pry_sdk.py`.

import {
  optionUsd,
  parseRetryAfter,
  PryNetworkError,
  PryPaymentRequired,
  PryRateLimitError,
  toPryError,
} from "./errors.ts";
import type {
  BatchRequest,
  BatchResponse,
  CrawlRequest,
  CrawlResponse,
  ExtractResponse,
  MapRequest,
  MapResponse,
  PayCallback,
  RequestOptions,
  ScrapeOptions,
  ScrapeResponse,
  SearchRequest,
  SearchResponse,
  X402Challenge,
} from "./types.ts";

export const DEFAULT_BASE_URL = "http://localhost:8005";
const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);

export interface PryClientConfig {
  /** Sent as `Authorization: Bearer <apiKey>`. Never commit this. */
  apiKey?: string;
  baseUrl?: string;
  /** Per-request timeout in milliseconds. Default 60000. */
  timeoutMs?: number;
  /** Retries for idempotent (GET) requests only. Default 2. */
  maxRetries?: number;
  /** Reject a 402 whose every accepted option costs more than this (USD). */
  maxPriceUsd?: number;
  /** Default 402 handler; without one a 402 throws `PryPaymentRequired`. */
  pay?: PayCallback;
  /** Injectable fetch — used by tests and non-standard runtimes. */
  fetch?: typeof globalThis.fetch;
}

type Body = Record<string, unknown> | string[] | BatchRequest;

/** Encode a payer result as the `PAYMENT-SIGNATURE` header value. */
function encodePayment(payment: string | Record<string, unknown>): string {
  if (typeof payment === "string") return payment;
  const bytes = new TextEncoder().encode(JSON.stringify(payment));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** Wait `ms` before a retry (kept out of `send` so tests can observe it). */
const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

/** Typed client for `POST /v1/{scrape,crawl,map,search,batch,extract}`. */
export class PryClient {
  readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly maxPriceUsd: number | undefined;
  private readonly pay: PayCallback | undefined;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(config: PryClientConfig = {}) {
    this.baseUrl = (config.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.headers = { "Content-Type": "application/json", Accept: "application/json" };
    if (config.apiKey) this.headers.Authorization = `Bearer ${config.apiKey}`;
    this.timeoutMs = config.timeoutMs ?? 60_000;
    this.maxRetries = Math.max(0, config.maxRetries ?? 2);
    this.maxPriceUsd = config.maxPriceUsd;
    this.pay = config.pay;
    this.fetchImpl = config.fetch ?? globalThis.fetch.bind(globalThis);
  }

  /** Scrape one URL (`POST /v1/scrape`). */
  async scrape(
    url: string,
    opts: ScrapeOptions & RequestOptions = {},
  ): Promise<ScrapeResponse> {
    const { signal, pay, headers, ...rest } = opts;
    return (await this.post("/v1/scrape", { url, ...rest }, { signal, pay, headers })) as
      ScrapeResponse;
  }

  /** Crawl a site; with `webhook` the call returns a job id (`POST /v1/crawl`). */
  async crawl(
    url: string,
    opts: Omit<CrawlRequest, "url"> & RequestOptions = {},
  ): Promise<CrawlResponse> {
    const { signal, pay, headers, ...rest } = opts;
    return (await this.post("/v1/crawl", { url, ...rest }, { signal, pay, headers })) as
      CrawlResponse;
  }

  /** Map a site's URLs (`POST /v1/map`). */
  async map(
    url: string,
    opts: Omit<MapRequest, "url"> & RequestOptions = {},
  ): Promise<MapResponse> {
    const { signal, pay, headers, ...rest } = opts;
    return (await this.post("/v1/map", { url, ...rest }, { signal, pay, headers })) as
      MapResponse;
  }

  /** Web search (`POST /v1/search`). */
  async search(
    query: string,
    opts: Omit<SearchRequest, "query"> & RequestOptions = {},
  ): Promise<SearchResponse> {
    const { signal, pay, headers, ...rest } = opts;
    return (await this.post("/v1/search", { query, ...rest }, { signal, pay, headers })) as
      SearchResponse;
  }

  /** Scrape up to 50 URLs (`POST /v1/batch`). */
  async batch(
    request: string[] | BatchRequest,
    opts: RequestOptions = {},
  ): Promise<BatchResponse> {
    return (await this.post("/v1/batch", request, opts)) as BatchResponse;
  }

  /** Extract named fields from a page (`POST /v1/extract`). */
  async extract(
    url: string,
    fields: Record<string, string>,
    opts: RequestOptions = {},
  ): Promise<ExtractResponse> {
    return (await this.post("/v1/extract", { url, fields }, opts)) as ExtractResponse;
  }

  /** Liveness check (`GET /health`). */
  async health(opts: RequestOptions = {}): Promise<Record<string, unknown>> {
    return (await this.request("GET", "/health", undefined, opts)) as Record<string, unknown>;
  }

  private async post(path: string, body: Body, opts: RequestOptions): Promise<unknown> {
    let res = await this.send("POST", path, body, opts);
    if (res.status === 402) res = await this.settle(res, path, body, opts);
    return this.readJson(res);
  }

  /** Guard, price-check, invoke the payer, and retry exactly once with proof. */
  private async settle(
    res: Response,
    path: string,
    body: Body,
    opts: RequestOptions,
  ): Promise<Response> {
    const challenge = (await this.json(res)) as X402Challenge;
    const normalised: X402Challenge = {
      ...challenge,
      x402Version: Number(challenge.x402Version ?? 1),
      accepts: Array.isArray(challenge.accepts) ? challenge.accepts : [],
    };
    this.guardPrice(normalised);
    const payer = opts.pay ?? this.pay;
    if (!payer) throw new PryPaymentRequired(normalised);
    const proof = encodePayment(await payer(normalised));
    return this.send("POST", path, body, {
      ...opts,
      headers: { "X-PAYMENT": proof, "PAYMENT-SIGNATURE": proof },
    });
  }

  private guardPrice(challenge: X402Challenge): void {
    const max = this.maxPriceUsd;
    if (max === undefined) return;
    const affordable = challenge.accepts.filter((accept) => optionUsd(accept) <= max);
    if (affordable.length > 0) {
      challenge.accepts = affordable;
      return;
    }
    const first = challenge.accepts[0];
    const cheapest = first ? optionUsd(first) : 0;
    throw new PryPaymentRequired(challenge, `price $${cheapest} > max $${max}`);
  }

  private async readJson(res: Response): Promise<unknown> {
    if (res.status === 429) {
      throw new PryRateLimitError(
        await this.problem(res),
        parseRetryAfter(res.headers.get("retry-after")),
      );
    }
    if (!res.ok) throw await this.problem(res);
    return this.json(res);
  }

  private async problem(res: Response) {
    const text = await res.text();
    const body = parseJson(text);
    return toPryError(res.status, body, text);
  }

  private async json(res: Response): Promise<unknown> {
    const text = await res.text();
    return text ? parseJson(text) : {};
  }

  private async send(
    method: string,
    path: string,
    body: Body | undefined,
    opts: RequestOptions,
  ): Promise<Response> {
    const idempotent = method === "GET";
    const attempts = idempotent ? this.maxRetries + 1 : 1;
    let lastError: unknown;
    for (let attempt = 0; attempt < attempts; attempt++) {
      try {
        const res = await this.once(method, path, body, opts);
        if (!idempotent || !RETRY_STATUS.has(res.status) || attempt === attempts - 1) {
          return res;
        }
      } catch (err) {
        if (!idempotent || attempt === attempts - 1) {
          throw err instanceof PryNetworkError
            ? err
            : new PryNetworkError(`${method} ${path} failed`, err);
        }
        lastError = err;
      }
      await sleep(Math.min(50 * 2 ** attempt, 2000));
    }
    throw new PryNetworkError(`${method} ${path} failed`, lastError);
  }

  private async request(
    method: string,
    path: string,
    body: Body | undefined,
    opts: RequestOptions,
  ): Promise<unknown> {
    return this.readJson(await this.send(method, path, body, opts));
  }

  private async once(
    method: string,
    path: string,
    body: Body | undefined,
    opts: RequestOptions,
  ): Promise<Response> {
    const headers = { ...this.headers, ...(opts.headers ?? {}) };
    const signal = opts.signal ?? AbortSignal.timeout(this.timeoutMs);
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (err) {
      throw new PryNetworkError(`${method} ${path} failed: ${String(err)}`, err);
    }
  }
}

/** JSON parse that degrades to the raw text instead of throwing. */
function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}
