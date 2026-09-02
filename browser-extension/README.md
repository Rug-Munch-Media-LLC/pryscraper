# Pry Browser Extension

One-click scraping from your browser. Sends the current page to your Pry server
(`/v1/scrape`) and shows the extracted content in the popup. Also supports
client-side extraction (prices, products, reviews, links, images, custom CSS
selectors) without hitting the server.

## Features

- **Scrape current page** — POSTs the active tab URL to your Pry server and
  displays the result. Errors (network, HTTP status, non-JSON responses,
  permission denials) are surfaced directly in the popup.
- **Extract from page** — runs a content script on the active tab and extracts
  structured data locally.
- **Destinations** — copy result to clipboard, or send to a configured
  destination via the Pry API.
- **Settings** — server URL (default `http://localhost:8002`) and optional API
  key, stored in `chrome.storage.sync`.

## Permissions

Minimal by design (Manifest V3):

- `activeTab`, `storage`, `scripting`, `notifications`
- Host access to the Pry server is **optional** (`optional_host_permissions`).
  The popup requests permission for your configured server origin on first
  scrape — no blanket `<all_urls>` access.

## Load unpacked

1. Open `chrome://extensions` (or `edge://extensions`, `brave://extensions`).
2. Enable **Developer mode**.
3. Click **Load unpacked** and select this `browser-extension/` directory.
4. Open the popup → **Settings** tab → set your Pry server URL and API key →
   **Save Settings**.
5. On the first scrape, approve the host-permission prompt for your server.

## Files

| File | Purpose |
|------|---------|
| `manifest.json` | MV3 manifest, minimal permissions |
| `background.js` | Service worker: scrape requests, default settings |
| `popup.html` / `popup.js` | Popup UI: scrape, extract, destinations, settings |
| `icons/` | Toolbar + store icons (16/48/128) |
