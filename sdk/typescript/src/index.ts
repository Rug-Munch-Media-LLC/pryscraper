// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
//
// Public surface. Everything a caller needs is re-exported here.

export {
  DEFAULT_BASE_URL,
  PryClient,
  type PryClientConfig,
} from "./client.ts";
export {
  optionUsd,
  parseRetryAfter,
  PryError,
  PryNetworkError,
  PryPaymentRequired,
  PryRateLimitError,
} from "./errors.ts";
export {
  DEFAULT_MCP_URL,
  PryMcpClient,
  PryMcpError,
  type McpContentBlock,
  type McpTool,
  type McpToolResult,
  type PryMcpConfig,
} from "./mcp.ts";
export type {
  BatchPage,
  BatchRequest,
  BatchResponse,
  CrawlPage,
  CrawlRequest,
  CrawlResponse,
  ExtractRequest,
  ExtractResponse,
  MapLink,
  MapRequest,
  MapResponse,
  PayCallback,
  ProblemDetails,
  RequestOptions,
  ScrapeData,
  ScrapeMetadata,
  ScrapeOptions,
  ScrapeResponse,
  SearchRequest,
  SearchResponse,
  SearchResult,
  X402Accept,
  X402Challenge,
} from "./types.ts";
