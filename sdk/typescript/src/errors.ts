// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
//
// Typed errors. The Python reference is `src/pry/api/pry_sdk.py`
// (`PryError`, `PaymentRequired`, `_problem`, `parse_challenge`).

import type { ProblemDetails, X402Accept, X402Challenge } from "./types.ts";

/** Any non-2xx response, or a transport failure (`status === 0`). */
export class PryError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly body: unknown;
  readonly requestId?: string;

  constructor(
    status: number,
    code = "",
    detail = "",
    body: unknown = undefined,
    requestId?: string,
  ) {
    super(`${status} ${code || "error"}: ${detail}`.replace(/: $/, ""));
    this.name = "PryError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.body = body;
    this.requestId = requestId;
  }
}

/**
 * HTTP 402 with the parsed x402 challenge. Branch on this — never on a
 * status-code string.
 */
export class PryPaymentRequired extends PryError {
  readonly challenge: X402Challenge;
  /** True when the server asked for an invoice/subscription settlement. */
  readonly invoiceRequired: boolean;
  /** Correlation id from the challenge body, when the server supplied one. */
  readonly paymentId: string;
  readonly accepts: X402Accept[];

  constructor(challenge: X402Challenge, reason = "payment required") {
    super(402, "payment_required", reason, challenge);
    this.name = "PryPaymentRequired";
    this.challenge = challenge;
    this.invoiceRequired = challenge.invoice_required === true;
    this.paymentId = typeof challenge.payment_id === "string" ? challenge.payment_id : "";
    this.accepts = Array.isArray(challenge.accepts) ? challenge.accepts : [];
  }
}

/** HTTP 429. `retryAfterSeconds` is parsed from the `Retry-After` header. */
export class PryRateLimitError extends PryError {
  readonly retryAfterSeconds: number | undefined;

  constructor(error: PryError, retryAfterSeconds: number | undefined) {
    super(error.status, error.code, error.detail, error.body, error.requestId);
    this.name = "PryRateLimitError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** The request never reached the server (DNS, reset, abort). `status === 0`. */
export class PryNetworkError extends PryError {
  override readonly cause?: unknown;

  constructor(detail: string, cause?: unknown) {
    super(0, "network_error", detail);
    this.name = "PryNetworkError";
    this.cause = cause;
  }
}

/** Parse `Retry-After` as delta-seconds or an HTTP date. */
export function parseRetryAfter(raw: string | null): number | undefined {
  if (!raw) return undefined;
  const seconds = Number(raw.trim());
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const at = Date.parse(raw);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, Math.round((at - Date.now()) / 1000));
}

/** Status-derived fallback when a proxy or middleware omits `code`. */
const STATUS_CODES: Record<number, string> = {
  400: "bad_request",
  401: "unauthorized",
  402: "payment_required",
  403: "forbidden",
  404: "not_found",
  409: "conflict",
  422: "unprocessable_entity",
  429: "too_many_requests",
  500: "internal_error",
  502: "bad_gateway",
  503: "service_unavailable",
  504: "gateway_timeout",
};

/** Build a `PryError` from a problem body, preferring RFC 7807 fields. */
export function toPryError(status: number, body: unknown, text: string): PryError {
  const p = (body && typeof body === "object" ? body : {}) as ProblemDetails;
  const code = p.code || p.type || STATUS_CODES[status] || "";
  const detail = p.detail || p.title || text.slice(0, 300) || `HTTP ${status}`;
  return new PryError(status, String(code), String(detail), body, p.request_id);
}

/** Normalise a 402 body into a `PryPaymentRequired`. */
export function toPaymentRequired(body: unknown, reason?: string): PryPaymentRequired {
  const raw = (body && typeof body === "object" ? body : {}) as X402Challenge;
  const accepts = Array.isArray(raw.accepts)
    ? raw.accepts.filter((a): a is X402Accept => Boolean(a) && typeof a === "object")
    : [];
  return new PryPaymentRequired(
    { ...raw, x402Version: Number(raw.x402Version ?? 1), accepts },
    reason,
  );
}

/**
 * USD value of one accept entry. Mirrors `_option_usd` in the Python SDK:
 * an explicit `amount_usd`/`price_usd` wins, else atomic units / 10^decimals
 * (6 by default, i.e. USDC).
 */
export function optionUsd(accept: X402Accept): number {
  const extra = (accept.extra ?? {}) as Record<string, unknown>;
  const explicit = (accept as unknown as Record<string, unknown>).amount_usd ??
    (accept as unknown as Record<string, unknown>).price_usd;
  if (explicit !== undefined && explicit !== null) return Number(explicit) || 0;
  const decimals = Number(extra.decimals ?? 6);
  const atomic = Number(accept.maxAmountRequired ?? 0);
  if (!Number.isFinite(decimals) || !Number.isFinite(atomic)) return 0;
  return atomic / 10 ** decimals;
}
