[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# Pry Monitor — WordPress Plugin

Competitor price & content monitoring directly in your WordPress dashboard. Track competitors, get email alerts on changes, and sync competitor products to WooCommerce.

## Features

- **Dashboard** — At-a-glance stats: active monitors, monthly cost, competitors tracked
- **Competitors** — Add/remove competitor URLs to watch; bulk scan all at once
- **Monitors** — View Pry server monitors with status, check count, and last run time
- **Settings** — Configure Pry server URL, API key, and check interval
- **WooCommerce Sync** — Import competitor products as hidden WooCommerce products for reference
- **Scheduled Checks** — Hourly WP-Cron checks with email alerts on content changes

## Requirements

- WordPress 6.0+
- WooCommerce 8.0+ (optional, for product sync)
- Pry server instance (local or remote)

## Installation

1. Upload the `pry-monitor` folder to `/wp-content/plugins/`
2. Activate via WordPress **Plugins** page
3. Go to **Pry Monitor → Settings** and configure your Pry server URL

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Pry Server URL | `http://localhost:8002` | Your Pry API server address |
| API Key | *(empty)* | Bearer token (leave blank if auth disabled) |
| Check Interval | 60 min | How often to check competitors for changes |

## Usage

1. **Add competitors** under **Pry Monitor → Competitors** with a name + URL
2. **View monitors** under **Pry Monitor → Monitors** to see Pry server status
3. **Enable WooCommerce sync** under **Pry Monitor → Woo Sync** to import competitor products
4. **Email alerts** are sent to the WordPress admin email when competitors change content

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/costing/dashboard` | GET | Monthly cost stats |
| `/v1/monitors` | GET | Monitor list |
| `/v1/compliance/check` | POST | Validate competitor page |
| `/v1/freshness/check` | POST | Detect content changes |
| `/v1/scrape` | POST | Extract product data (WooCommerce) |

## Development

```bash
# Lint with PHP CodeSniffer
phpcs --standard=WordPress pry-monitor.php

# Check for security issues
phpcs --standard=WordPress-VIP-Go pry-monitor.php
```

## Changelog

### 1.0.0
- Initial release
- Dashboard with stats grid
- Competitor CRUD management
- Monitor list view from Pry API
- Settings page with server config
- WooCommerce product import
- WP-Cron hourly checks with email alerts
