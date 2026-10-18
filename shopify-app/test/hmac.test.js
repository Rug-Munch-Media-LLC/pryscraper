// SPDX-License-Identifier: MIT
// HMAC verification tests for the Pry Shopify app.
const test = require("node:test");
const assert = require("node:assert");
const crypto = require("crypto");
const {
	verifyQueryHmac,
	verifyWebhookHmac,
	validateShop,
	escapeHtml,
} = require("../server/server.js");

const SECRET = "test-shopify-secret";

function queryHmac(query, key = SECRET) {
	const message = Object.keys(query)
		.sort()
		.map((k) => `${k}=${query[k]}`)
		.join("&");
	return crypto.createHmac("sha256", key).update(message).digest("hex");
}

function webhookHmac(body, key = SECRET) {
	return crypto.createHmac("sha256", key).update(body).digest("base64");
}

test("query HMAC accepts a correctly signed callback", () => {
	const query = {
		shop: "pry-test.myshopify.com",
		code: "abc123",
		timestamp: "1700000000",
	};
	query.hmac = queryHmac(query);
	assert.strictEqual(verifyQueryHmac(query, SECRET), true);
});

test("query HMAC rejects a tampered shop", () => {
	const query = { shop: "pry-test.myshopify.com", code: "abc123" };
	query.hmac = queryHmac(query);
	assert.strictEqual(
		verifyQueryHmac({ ...query, shop: "evil.myshopify.com" }, SECRET),
		false,
	);
});

test("query HMAC rejects a wrong secret", () => {
	const query = { shop: "pry-test.myshopify.com", code: "abc123" };
	query.hmac = queryHmac(query, "other-secret");
	assert.strictEqual(verifyQueryHmac(query, SECRET), false);
});

test("query HMAC rejects a missing hmac", () => {
	assert.strictEqual(
		verifyQueryHmac({ shop: "pry-test.myshopify.com" }, SECRET),
		false,
	);
});

test("webhook HMAC accepts the exact raw body", () => {
	const body = Buffer.from(
		JSON.stringify({ shop: "pry-test.myshopify.com", productId: 1 }),
	);
	assert.strictEqual(verifyWebhookHmac(body, webhookHmac(body), SECRET), true);
});

test("webhook HMAC rejects a modified body", () => {
	const body = Buffer.from(
		JSON.stringify({ shop: "pry-test.myshopify.com", productId: 1 }),
	);
	const header = webhookHmac(body);
	const tampered = Buffer.from(
		JSON.stringify({ shop: "pry-test.myshopify.com", productId: 2 }),
	);
	assert.strictEqual(verifyWebhookHmac(tampered, header, SECRET), false);
});

test("webhook HMAC rejects missing header or secret", () => {
	const body = Buffer.from("{}");
	assert.strictEqual(verifyWebhookHmac(body, undefined, SECRET), false);
	assert.strictEqual(verifyWebhookHmac(body, webhookHmac(body), ""), false);
});

test("shop validation only accepts <name>.myshopify.com", () => {
	assert.strictEqual(validateShop("pry-test.myshopify.com"), true);
	assert.strictEqual(validateShop("evil.com"), false);
	assert.strictEqual(validateShop("evil.com/x.myshopify.com"), false);
	assert.strictEqual(validateShop("../etc/passwd"), false);
	assert.strictEqual(validateShop(undefined), false);
});

test("scraped HTML is escaped before storage", () => {
	assert.strictEqual(
		escapeHtml('<script>alert("x")</script>'),
		"&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;",
	);
});
