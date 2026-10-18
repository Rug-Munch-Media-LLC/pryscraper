// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
// Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
// Licensed under MIT. See LICENSE.
// Pry Browser Extension — Background Service Worker
// All scraping is performed by popup.js; this worker only seeds defaults.
chrome.runtime.onInstalled.addListener(() => {
	chrome.storage.sync.get(["pryServerUrl"], (result) => {
		if (!result.pryServerUrl) {
			chrome.storage.sync.set({ pryServerUrl: "http://localhost:8002" });
		}
	});
});
