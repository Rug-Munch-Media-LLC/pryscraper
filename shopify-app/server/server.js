// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
// Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
// Licensed under MIT. See LICENSE.
// Pry Shopify App — Express backend: OAuth, product import, webhooks.

const express = require("express");
const crypto = require("crypto");

const app = express();
const PORT = process.env.PORT || 3000;
const SHOP_RE = /^[a-z0-9][a-z0-9-]*\.myshopify\.com$/;
// In-memory token store (single-process only); replace with an encrypted store in production.
const tokens = new Map();

const secret = () => process.env.SHOPIFY_API_SECRET || "";
const pryApiUrl = () => process.env.PRY_API_URL || "http://localhost:8002";

// Capture the raw body: webhook HMAC must cover the exact bytes Shopify sent.
app.use(
	express.json({
		limit: "1mb",
		verify: (req, _res, buf) => {
			req.rawBody = buf;
		},
	}),
);

const validateShop = (shop) => typeof shop === "string" && SHOP_RE.test(shop);

function safeEqual(a, b) {
	if (typeof a !== "string" || typeof b !== "string") return false;
	const ab = Buffer.from(a);
	const bb = Buffer.from(b);
	return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

// App HMAC: sorted query params (excluding hmac/signature), hex HMAC-SHA256.
function verifyQueryHmac(query, key) {
	const { hmac, signature, ...rest } = query || {};
	if (!hmac || !key) return false;
	const message = Object.keys(rest)
		.sort()
		.map((k) => `${k}=${Array.isArray(rest[k]) ? rest[k].join(",") : rest[k]}`)
		.join("&");
	return safeEqual(
		crypto.createHmac("sha256", key).update(message).digest("hex"),
		hmac,
	);
}

// Webhook HMAC: base64 HMAC-SHA256 over the raw request body.
function verifyWebhookHmac(rawBody, header, key) {
	if (!header || !key || rawBody === undefined) return false;
	const digest = crypto
		.createHmac("sha256", key)
		.update(rawBody)
		.digest("base64");
	return safeEqual(digest, header);
}

function escapeHtml(value) {
	return String(value)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

// ── OAuth: begin install ──
app.get("/auth", (req, res) => {
	const { shop } = req.query;
	if (!validateShop(shop))
		return res.status(400).json({ error: "Invalid shop parameter" });
	const redirectUri = encodeURIComponent(`${process.env.HOST}/auth/callback`);
	const clientId = encodeURIComponent(process.env.SHOPIFY_API_KEY || "");
	res.redirect(
		`https://${shop}/admin/oauth/authorize?client_id=${clientId}&scope=write_products,read_products&redirect_uri=${redirectUri}`,
	);
});

// ── OAuth: callback — verify HMAC, then exchange the code for a token ──
app.get("/auth/callback", async (req, res) => {
	const { shop, code } = req.query;
	if (!validateShop(shop) || !code)
		return res.status(400).json({ error: "Invalid callback parameters" });
	if (!verifyQueryHmac(req.query, secret()))
		return res.status(401).json({ error: "HMAC validation failed" });
	try {
		const response = await fetch(`https://${shop}/admin/oauth/access_token`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				client_id: process.env.SHOPIFY_API_KEY,
				client_secret: secret(),
				code,
			}),
		});
		const data = await response.json();
		if (!response.ok || !data.access_token)
			return res.status(502).json({ error: "Token exchange failed" });
		tokens.set(shop, data.access_token);
		res.json({ success: true, shop });
	} catch (err) {
		res.status(500).json({ error: err.message });
	}
});

// ── Import one product: scrape via Pry, create in Shopify ──
async function importOne(shop, productUrl) {
	const pryResponse = await fetch(`${pryApiUrl()}/v1/scrape`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ url: productUrl, bypassCloudflare: true }),
	});
	const pryData = await pryResponse.json();
	if (!pryData.success)
		throw new Error(`Pry scrape failed: ${pryData.error || "unknown"}`);
	const bodyHtml = `<div>${escapeHtml(String(pryData.data.content || "").substring(0, 5000))}</div>`;
	const payload = {
		product: {
			title: String(pryData.data.title || "Imported Product").substring(0, 255),
			body_html: bodyHtml,
			vendor: "Competitor Import",
			product_type: "Reference",
			status: "draft",
			metafields_global: [
				{
					key: "original_source",
					value: productUrl,
					type: "single_line_text_field",
					namespace: "pry",
				},
			],
		},
	};
	const shopifyResponse = await fetch(
		`https://${shop}/admin/api/2024-01/products.json`,
		{
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Shopify-Access-Token": tokens.get(shop),
			},
			body: JSON.stringify(payload),
		},
	);
	const shopifyData = await shopifyResponse.json();
	if (!shopifyResponse.ok)
		throw new Error(`Shopify API error: ${JSON.stringify(shopifyData)}`);
	return shopifyData.product;
}

function requireInstalled(req, res) {
	const { shop } = req.body || {};
	if (!validateShop(shop)) {
		res.status(400).json({ error: "Invalid shop parameter" });
		return null;
	}
	if (!tokens.has(shop)) {
		res.status(401).json({ error: "Shop not installed" });
		return null;
	}
	return shop;
}

app.post("/import-product", async (req, res) => {
	const shop = requireInstalled(req, res);
	if (!shop) return;
	const { productUrl } = req.body;
	if (!productUrl) return res.status(400).json({ error: "Missing productUrl" });
	try {
		const product = await importOne(shop, productUrl);
		res.json({
			success: true,
			shopify_product_id: product.id,
			product_url: `https://${shop}/admin/products/${product.id}`,
			title: product.title,
		});
	} catch (err) {
		res.status(502).json({ error: err.message });
	}
});

app.post("/bulk-import", async (req, res) => {
	const shop = requireInstalled(req, res);
	if (!shop) return;
	const { urls } = req.body;
	if (!Array.isArray(urls))
		return res.status(400).json({ error: "Missing urls" });
	const results = [];
	for (const url of urls) {
		try {
			const product = await importOne(shop, url);
			results.push({ url, success: true, product_id: product.id });
		} catch (err) {
			results.push({ url, success: false, error: err.message });
		}
	}
	res.json({
		success: true,
		imported: results.filter((r) => r.success).length,
		failed: results.filter((r) => !r.success).length,
		results,
	});
});

// ── Webhooks: every handler requires a valid X-Shopify-Hmac-Sha256 ──
function verifyWebhook(req, res) {
	const ok = verifyWebhookHmac(
		req.rawBody,
		req.get("X-Shopify-Hmac-Sha256"),
		secret(),
	);
	if (!ok) res.status(401).json({ error: "Invalid webhook HMAC" });
	return ok;
}

app.post("/webhook/pry-monitor", async (req, res) => {
	if (!verifyWebhook(req, res)) return;
	const { shop, productId, update } = req.body || {};
	if (!validateShop(shop) || !tokens.has(shop))
		return res.status(400).json({ error: "Unknown shop" });
	try {
		await fetch(
			`https://${shop}/admin/api/2024-01/products/${productId}.json`,
			{
				method: "PUT",
				headers: {
					"Content-Type": "application/json",
					"X-Shopify-Access-Token": tokens.get(shop),
				},
				body: JSON.stringify({
					product: {
						body_html: update ? escapeHtml(update) : undefined,
						metafields_global: [
							{
								key: "last_monitor_update",
								value: new Date().toISOString(),
								type: "single_line_text_field",
								namespace: "pry",
							},
						],
					},
				}),
			},
		);
		res.json({ success: true });
	} catch (err) {
		res.status(500).json({ error: err.message });
	}
});

// ── Mandatory GDPR webhooks: verified then acknowledged (no-op) ──
for (const topic of [
	"customers/data_request",
	"customers/redact",
	"shop/redact",
]) {
	app.post(`/webhook/${topic}`, (req, res) => {
		if (!verifyWebhook(req, res)) return;
		res.status(200).json({ success: true });
	});
}

if (require.main === module) {
	app.listen(PORT, () =>
		console.log(`Pry Shopify app running on port ${PORT}`),
	);
}

module.exports = {
	app,
	validateShop,
	verifyQueryHmac,
	verifyWebhookHmac,
	escapeHtml,
	tokens,
};
