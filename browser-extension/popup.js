// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Rug Munch Media LLC
// Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
// Licensed under MIT. See LICENSE.
// Pry Browser Extension — Popup Script
document.addEventListener("DOMContentLoaded", () => {
	loadSettings();

	// Tab switching
	document.querySelectorAll(".tab").forEach((tab) => {
		tab.addEventListener("click", () => {
			document.querySelectorAll(".tab").forEach((t) => {
				t.classList.remove("active");
			});
			document.querySelectorAll(".tab-content").forEach((c) => {
				c.style.display = "none";
			});
			tab.classList.add("active");
			document.getElementById(`tab-${tab.dataset.tab}`).style.display = "block";
		});
	});

	// Scrape current page
	document
		.getElementById("scrape-current")
		.addEventListener("click", scrapeCurrentPage);

	// Extract from page
	document
		.getElementById("extract-current")
		.addEventListener("click", extractFromPage);

	// Show custom selector field
	document
		.getElementById("extract-type")
		.addEventListener("change", function () {
			document.getElementById("custom-selector-field").style.display =
				this.value === "custom" ? "block" : "none";
		});

	// Save settings
	document
		.getElementById("save-settings")
		.addEventListener("click", saveSettings);

	// Destination buttons
	document.querySelectorAll(".dest-btn").forEach((btn) => {
		btn.addEventListener("click", function () {
			document.querySelectorAll(".dest-btn").forEach((b) => {
				b.classList.remove("active");
			});
			this.classList.add("active");
		});
	});
});

function loadSettings() {
	chrome.storage.sync.get(
		["pryServerUrl", "pryApiKey", "defaultDest"],
		(result) => {
			document.getElementById("pry-server-url").value =
				result.pryServerUrl || "https://localhost:8002";
			document.getElementById("pry-api-key").value = result.pryApiKey || "";
			if (result.defaultDest) {
				document.getElementById("default-destination").value =
					result.defaultDest;
			}
		},
	);
}

function saveSettings() {
	chrome.storage.sync.set(
		{
			pryServerUrl: document.getElementById("pry-server-url").value,
			pryApiKey: document.getElementById("pry-api-key").value,
			defaultDest: document.getElementById("default-destination").value,
		},
		() => {
			showStatus("settings-status", "Settings saved!", "success");
		},
	);
}

// Ensure the extension has host permission for the configured server URL.
// Static host_permissions are empty; the user grants access on first use.
async function ensureHostPermission(serverUrl) {
	try {
		const origin = `${new URL(serverUrl).origin}/*`;
		const has = await chrome.permissions.contains({ origins: [origin] });
		if (has) return true;
		const granted = await chrome.permissions.request({ origins: [origin] });
		if (!granted) {
			showStatus("scrape-status", `Permission denied for ${origin}`, "error");
			return false;
		}
		return true;
	} catch (err) {
		showStatus("scrape-status", `Permission error: ${err.message}`, "error");
		return false;
	}
}

function scrapeCurrentPage() {
	chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
		const url = tabs[0].url;
		showStatus("scrape-status", "Scraping...", "loading");

		chrome.storage.sync.get(["pryServerUrl", "pryApiKey"], async (config) => {
			const serverUrl = config.pryServerUrl || "https://localhost:8002";
			if (!(await ensureHostPermission(serverUrl))) return;
			try {
				const response = await fetch(`${serverUrl}/v1/scrape`, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						...(config.pryApiKey
							? { Authorization: `Bearer ${config.pryApiKey}` }
							: {}),
					},
					body: JSON.stringify({ url: url, bypassCloudflare: true }),
				});
				let data;
				try {
					data = await response.json();
				} catch {
					throw new Error(
						`Server returned non-JSON response (HTTP ${response.status})`,
					);
				}
				if (!response.ok && !data.error) {
					data = { success: false, error: `HTTP ${response.status}` };
				}

				if (data.success) {
					const content = data.data.content || data.data;
					document.getElementById("scrape-result").style.display = "block";
					document.getElementById("scrape-result").textContent =
						typeof content === "string"
							? content.substring(0, 2000)
							: JSON.stringify(content, null, 2);

					// Send to destination if active
					const activeDest = document.querySelector(".dest-btn.active");
					if (activeDest) {
						sendToDestination(activeDest.dataset.dest, content, config);
					}

					showStatus("scrape-status", "Scraped successfully!", "success");
				} else {
					showStatus(
						"scrape-status",
						`Scrape failed: ${data.error || "Unknown error"}`,
						"error",
					);
				}
			} catch (err) {
				showStatus("scrape-status", `Error: ${err.message}`, "error");
			}
		});
	});
}

function extractFromPage() {
	chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
		const _url = tabs[0].url;
		const extractType = document.getElementById("extract-type").value;

		// Inject content script to extract data
		chrome.scripting.executeScript(
			{
				target: { tabId: tabs[0].id },
				func: extractDataFromPage,
				args: [extractType, document.getElementById("custom-selector").value],
			},
			(results) => {
				if (results?.[0]?.result) {
					document.getElementById("extract-result").style.display = "block";
					document.getElementById("extract-result").textContent =
						JSON.stringify(results[0].result, null, 2);
					showStatus(
						"extract-status",
						`Extracted ${results[0].result.length} items`,
						"success",
					);
				} else {
					showStatus("extract-status", "No data found", "error");
				}
			},
		);
	});
}

function extractDataFromPage(type, customSelector) {
	const data = [];

	if (type === "prices") {
		document
			.querySelectorAll('[class*="price"], [class*="cost"], .a-price, .price')
			.forEach((el) => {
				data.push(el.textContent.trim());
			});
	} else if (type === "products") {
		document
			.querySelectorAll('[class*="product"], [class*="item"], article, .card')
			.forEach((el) => {
				data.push({
					title:
						el
							.querySelector('h2, h3, [class*="title"], [class*="name"]')
							?.textContent?.trim() || "",
					price:
						el.querySelector('[class*="price"]')?.textContent?.trim() || "",
					link: el.querySelector("a")?.href || "",
				});
			});
	} else if (type === "reviews") {
		document
			.querySelectorAll('[class*="review"], [class*="testimonial"]')
			.forEach((el) => {
				data.push({
					text: el.textContent.trim().substring(0, 200),
					rating:
						el
							.querySelector('[class*="star"], [class*="rating"]')
							?.textContent?.trim() || "",
				});
			});
	} else if (type === "links") {
		document.querySelectorAll("a[href]").forEach((el) => {
			data.push({ text: el.textContent.trim(), href: el.href });
		});
	} else if (type === "images") {
		document.querySelectorAll("img[src]").forEach((el) => {
			data.push({ alt: el.alt, src: el.src });
		});
	} else if (type === "custom") {
		document.querySelectorAll(customSelector).forEach((el) => {
			data.push(el.textContent.trim());
		});
	}

	return data.filter(
		(d) =>
			d &&
			(typeof d === "string" ? d.length > 0 : Object.values(d).some((v) => v)),
	);
}

async function sendToDestination(dest, content, config) {
	if (dest === "clipboard") {
		navigator.clipboard.writeText(
			typeof content === "string" ? content : JSON.stringify(content, null, 2),
		);
		return;
	}

	// For Slack/Email, would use the Pry API
	try {
		await fetch(`${config.pryServerUrl}/v1/destination/send`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				...(config.pryApiKey
					? { Authorization: `Bearer ${config.pryApiKey}` }
					: {}),
			},
			body: JSON.stringify({
				destination: dest,
				data: { content: content },
				config: {},
			}),
		});
	} catch (err) {
		console.error("Failed to send to destination:", err);
		showStatus("scrape-status", `Send failed: ${err.message}`, "error");
	}
}

function showStatus(id, message, type) {
	const el = document.getElementById(id);
	el.textContent = message;
	el.className = `status ${type}`;
	el.style.display = "block";
	setTimeout(() => {
		el.style.display = "none";
	}, 5000);
}
