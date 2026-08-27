# Scrape API

Scrape any URL to clean, readable markdown with automatic Cloudflare bypass.

## Endpoint

```
POST /v1/scrape
```

### Request

```json
{
  "url": "https://example.com/article",
  "formats": ["markdown"],
  "bypass_cloudflare": true,
  "js_render": false,
  "extract_schema": {
    "fields": [
      {"name": "title", "selector": "h1", "type": "string"},
      {"name": "price", "selector": ".price", "type": "number"}
    ]
  }
}
```

### Response (402 Payment Required)

```json
{
  "x402Version": 1,
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "maxAmountRequired": "1000",
    "resource": "https://api.[INTERNAL]/v1/scrape",
    "description": "Scrape any URL",
    "mint": "0x...",
    "payToAddress": "0x1E3AC01d0fdb976179790BDD02823196A92705C9",
    "asset": "USDC",
    "extra": {"name": "USDC", "verification": "eip3009"}
  }],
  "error": "Payment required"
}
```

### Response (200 OK after payment)

```json
{
  "success": true,
  "data": {
    "url": "https://example.com/article",
    "title": "Example Article",
    "content": "# Example\n\nClean markdown content...",
    "links": ["https://example.com/other"],
    "images": ["https://example.com/img.jpg"],
    "status_code": 200
  }
}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | (required) | URL to scrape |
| `formats` | array | `["markdown"]` | Output formats: `markdown`, `html`, `text`, `json` |
| `bypass_cloudflare` | boolean | `true` | Enable Cloudflare bypass |
| `js_render` | boolean | `false` | Render JavaScript (slower, handles SPAs) |
| `extract_schema` | object | (optional) | Structured extraction schema |

### Error Codes

| Code | Description |
|------|-------------|
| `402` | Payment required (x402) |
| `400` | Invalid request |
| `429` | Rate limit exceeded |
| `500` | Internal server error |
| `502` | All tiers failed (site unreachable) |
