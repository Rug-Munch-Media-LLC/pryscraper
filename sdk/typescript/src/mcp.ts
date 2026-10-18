// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
//
// `PryMcpClient` — a thin MCP client for Pry's `POST /mcp/` endpoint.
//
// It speaks MCP JSON-RPC 2.0 over streamable HTTP using the platform `fetch`
// (no SDK dependency to install and audit). The official SDK can be pointed at
// the same endpoint instead — see README "MCP".

import type { RequestOptions } from "./types.ts";

/** Public streamable-HTTP endpoint served by Pry (`/mcp` on the API). */
export const DEFAULT_MCP_URL = "https://api.pryscraper.com/mcp/";

/** An MCP protocol-level error (JSON-RPC `error`, not an HTTP status). */
export class PryMcpError extends Error {
  readonly code: number;
  readonly data: unknown;

  constructor(code: number, message: string, data: unknown = undefined) {
    super(`MCP ${code}: ${message}`);
    this.name = "PryMcpError";
    this.code = code;
    this.data = data;
  }
}

export interface PryMcpConfig {
  /** Full endpoint URL. Defaults to `DEFAULT_MCP_URL`. */
  url?: string;
  /** Convenience: `baseUrl` + `/mcp/` when `url` is omitted. */
  baseUrl?: string;
  apiKey?: string;
  /** Requested revision; the server replies with its own negotiated one. */
  protocolVersion?: string;
  timeoutMs?: number;
  fetch?: typeof globalThis.fetch;
}

export interface McpContentBlock {
  type: string;
  text?: string;
  [key: string]: unknown;
}

export interface McpToolResult {
  content: McpContentBlock[];
  isError?: boolean;
  structuredContent?: unknown;
}

export interface McpTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id?: number | string;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

/** MCP client for `POST /mcp/` — initialize, list tools, call tools. */
export class PryMcpClient {
  readonly url: string;
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof globalThis.fetch;
  private readonly protocolVersion: string;
  private sessionId = "";
  private nextId = 1;
  private initialized = false;

  constructor(config: PryMcpConfig = {}) {
    const base = (config.baseUrl ?? "").replace(/\/+$/, "");
    this.url = config.url ?? (base ? `${base}/mcp/` : DEFAULT_MCP_URL);
    this.headers = {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    };
    if (config.apiKey) this.headers.Authorization = `Bearer ${config.apiKey}`;
    this.timeoutMs = config.timeoutMs ?? 60_000;
    this.fetchImpl = config.fetch ?? globalThis.fetch.bind(globalThis);
    this.protocolVersion = config.protocolVersion ?? "2025-06-18";
  }

  /** Perform the MCP handshake once; subsequent calls reuse the session. */
  async initialize(opts: RequestOptions = {}): Promise<unknown> {
    if (this.initialized) return { alreadyInitialized: true };
    const result = await this.rpc(
      "initialize",
      {
        protocolVersion: this.protocolVersion,
        capabilities: {},
        clientInfo: { name: "pry-typescript-sdk", version: "0.1.0" },
      },
      opts,
    );
    this.initialized = true;
    return result;
  }

  /** List the tools the server exposes. */
  async listTools(opts: RequestOptions = {}): Promise<McpTool[]> {
    await this.initialize(opts);
    const result = (await this.rpc("tools/list", {}, opts)) as { tools?: McpTool[] };
    return result.tools ?? [];
  }

  /** Call one tool by name; returns content blocks verbatim. */
  async callTool(
    name: string,
    args: Record<string, unknown> = {},
    opts: RequestOptions = {},
  ): Promise<McpToolResult> {
    await this.initialize(opts);
    return (await this.rpc("tools/call", { name, arguments: args }, opts)) as McpToolResult;
  }

  /** Convenience wrapper over the `pry_scrape` tool. */
  async scrape(
    url: string,
    args: Record<string, unknown> = {},
    opts: RequestOptions = {},
  ): Promise<McpToolResult> {
    return this.callTool("pry_scrape", { url, ...args }, opts);
  }

  /** Convenience wrapper over the `pry_crawl` tool. */
  async crawl(
    url: string,
    args: Record<string, unknown> = {},
    opts: RequestOptions = {},
  ): Promise<McpToolResult> {
    return this.callTool("pry_crawl", { url, ...args }, opts);
  }

  private async rpc(
    method: string,
    params: Record<string, unknown>,
    opts: RequestOptions,
  ): Promise<unknown> {
    const id = this.nextId++;
    const headers = {
      ...this.headers,
      ...(this.sessionId ? { "Mcp-Session-Id": this.sessionId } : {}),
      ...(opts.headers ?? {}),
    };
    const signal = opts.signal ?? AbortSignal.timeout(this.timeoutMs);
    const res = await this.fetchImpl(this.url, {
      method: "POST",
      headers,
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
      signal,
    });
    const session = res.headers.get("mcp-session-id");
    if (session) this.sessionId = session;
    if (!res.ok) throw new PryMcpError(res.status, `HTTP ${res.status} from ${method}`);
    const message = await readMessage(res, id);
    if (message.error) {
      throw new PryMcpError(message.error.code, message.error.message, message.error.data);
    }
    return message.result;
  }
}

/** Read a JSON or SSE body and pick the frame matching `id`. */
async function readMessage(res: Response, id: number): Promise<JsonRpcResponse> {
  const text = await res.text();
  const type = res.headers.get("content-type") ?? "";
  const frames = type.includes("text/event-stream")
    ? text
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
    : [text];
  for (let i = frames.length - 1; i >= 0; i--) {
    const frame = frames[i];
    if (frame === undefined) continue;
    try {
      const parsed = JSON.parse(frame) as JsonRpcResponse;
      if (parsed && (parsed.id === id || parsed.id === undefined)) return parsed;
    } catch {
      // Not a JSON frame (ping/comment) — keep scanning.
    }
  }
  throw new PryMcpError(-32700, `no JSON-RPC response for id ${id}`);
}
