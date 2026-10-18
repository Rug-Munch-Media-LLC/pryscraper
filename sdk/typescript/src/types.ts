// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
//
// Request and response models derived from the live API surface:
//   src/pry/api/routers/scraping/scraping_models.py   (ScrapeRequest, CrawlRequest)
//   src/pry/api/routers/scraping/search_map.py        (SearchRequest, MapRequest)
//   src/pry/api/routers/scraping/batch_routes.py      (POST /v1/batch)
//   src/pry/api/routers/scraping/extraction.py        (POST /v1/extract)
//   src/pry/api/exception_handlers.py                 (RFC 7807 error body)
//   src/pry/payments/x402/scheme/pricing/             (402 challenge + accepts)
//
// Field names are the wire names (camelCase where the API uses camelCase).
// Do not add fields the server does not emit.

/** Options accepted by `POST /v1/scrape` alongside `url`. */
export interface ScrapeOptions {
  /** Firecrawl format selectors: markdown, html, rawHtml, links, images, screenshot, pdf. */
  formats?: string[];
  onlyMainContent?: boolean | null;
  /** Per-request budget in seconds across the anti-bot tier chain. Default 120. */
  timeout?: number | null;
  bypassCloudflare?: boolean | null;
  jsRender?: boolean | null;
  /** Field name -> natural-language description, extracted by the LLM extractor. */
  jsonSchema?: Record<string, string> | null;
  /** Window into the extracted markdown. */
  offset?: number;
  limit?: number;
}

export interface ScrapeMetadata {
  url: string;
  method: string;
  title: string;
  description: string;
  markdown_quality: number;
  formats: string[];
}

export interface ScrapeData {
  markdown: string;
  metadata: ScrapeMetadata;
  /** Present only when the matching format was requested. */
  rawHtml?: string;
  html?: string;
  links?: string[];
  images?: string[];
  /** Base64 payloads for the `screenshot` / `pdf` media formats. */
  screenshot?: string;
  pdf?: string;
  /** Present when `jsonSchema` was supplied. */
  json?: Record<string, unknown>;
}

export interface ScrapeResponse {
  success: true;
  data: ScrapeData;
}

export interface CrawlRequest {
  url: string;
  maxPages?: number | null;
  maxDepth?: number | null;
  scrapeOptions?: Record<string, unknown> | null;
  /** When set, the crawl is queued and the call returns a job id instead of pages. */
  webhook?: string | null;
}

/** One crawled page as returned by the engine (shape owned by the scraper). */
export type CrawlPage = Record<string, unknown>;

export interface CrawlResponse {
  success: true;
  data: {
    /** `"sync"` for the inline crawl, or a job id for a webhook crawl. */
    id: string;
    url?: string;
    pages?: CrawlPage[];
    status?: "pending";
  };
}

export interface MapRequest {
  url: string;
  /** Case-insensitive substring filter over discovered URLs. */
  search?: string;
  ignoreSitemap?: boolean | null;
  sitemapOnly?: boolean | null;
  limit?: number | null;
}

export interface MapLink {
  url: string;
}

/** Canonical contract: `{url, links, count}`. `success`/`data` are deprecated aliases. */
export interface MapResponse {
  url: string;
  links: MapLink[];
  count: number;
}

export interface SearchRequest {
  query: string;
  limit?: number;
  /** Only `"web"` is implemented; anything else is rejected with 400. */
  sources?: string[];
  /** `{ formats: ["markdown"] }` also scrapes every hit. */
  scrapeOptions?: Record<string, unknown> | null;
}

export interface SearchResult {
  url: string;
  title: string;
  description: string;
  markdown?: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

/**
 * `POST /v1/batch` accepts a bare array of URLs (legacy) or an object.
 * Setting `async` or `webhook` queues the job instead of returning pages.
 */
export interface BatchRequest {
  urls: string[];
  timeout?: number;
  async?: boolean;
  webhook?: string | null;
}

export interface BatchPage {
  url: string;
  markdown?: string;
  method?: string;
  /** Per-URL failure, reported inline rather than failing the whole batch. */
  error?: string;
}

export interface BatchResponse {
  success: true;
  id?: string;
  status?: string;
  data: {
    pages?: BatchPage[];
    total?: number;
    id?: string;
  };
}

export interface ExtractRequest {
  url: string;
  /** Field name -> natural-language description. */
  fields: Record<string, string>;
}

export interface ExtractResponse {
  success: true;
  data: {
    url: string;
    fields: Record<string, unknown>;
  };
}

/** RFC 7807 problem body emitted by `src/pry/api/exception_handlers.py`. */
export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  request_id?: string;
  instance?: string;
  timestamp?: string;
  code?: string;
}

/** One payable option inside a 402 challenge. */
export interface X402Accept {
  scheme: string;
  /** CAIP-2 network id, e.g. `eip155:8453`. */
  network: string;
  /** Atomic units as a decimal string. */
  maxAmountRequired: string;
  resource?: string;
  description?: string;
  mimeType?: string;
  payToAddress: string;
  asset: string;
  extra?: Record<string, unknown>;
}

/** Parsed x402 challenge returned with HTTP 402. */
export interface X402Challenge {
  x402Version: number;
  accepts: X402Accept[];
  description?: string;
  instructions?: string;
  error?: string;
  /** True when the 402 asks for an invoice/subscription settlement. */
  invoice_required?: boolean;
  /** Server- or client-issued payment correlation id, when present. */
  payment_id?: string;
  [key: string]: unknown;
}

/** Options for a single call, overriding client defaults. */
export interface RequestOptions {
  signal?: AbortSignal;
  /** Overrides the client-level payment callback for this call only. */
  pay?: PayCallback;
  /** Extra request headers (e.g. `X-PAYMENT`, `PAYMENT-SIGNATURE`). */
  headers?: Record<string, string>;
}

/**
 * Resolves a 402 challenge into a `PAYMENT-SIGNATURE` payload (or a
 * pre-encoded string). Throwing from the callback propagates the throw.
 */
export type PayCallback = (
  challenge: X402Challenge,
) => string | Record<string, unknown> | Promise<string | Record<string, unknown>>;
