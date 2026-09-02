// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
// Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
// Licensed under MIT. See LICENSE.
// Pry Browser Extension — Background Service Worker
chrome.runtime.onInstalled.addListener(() => {
	chrome.storage.sync.get(["pryServerUrl"], (result) => {
		if (!result.pryServerUrl) {
			chrome.storage.sync.set({ pryServerUrl: "http://localhost:8002" });
		}
	});
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
	if (message.type === "scrape") {
		scrapeUrl(message.url, message.config).then(sendResponse);
		return true;
	}
});

async function scrapeUrl(url, config) {
	try {
		const response = await fetch(`${config.serverUrl}/v1/scrape`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}),
			},
			body: JSON.stringify({ url: url, bypassCloudflare: true }),
		});
		return await response.json();
	} catch (err) {
		return { success: false, error: err.message };
	}
}
