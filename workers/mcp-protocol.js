// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
// Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
// Licensed under MIT. See LICENSE.

/**
 * Highest MCP protocol revision this worker implements. Clients may request
 * anything older; the worker echoes the lower of the two.
 */
export const MCP_PROTOCOL_VERSION = "2026-07-28";

const VERSION_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Negotiate the protocol version: min(client requested, worker ceiling). */
export function negotiateProtocolVersion(clientVersion) {
	if (typeof clientVersion !== "string" || !VERSION_RE.test(clientVersion)) {
		return MCP_PROTOCOL_VERSION;
	}
	return clientVersion < MCP_PROTOCOL_VERSION
		? clientVersion
		: MCP_PROTOCOL_VERSION;
}
