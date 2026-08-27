# Crawl API

Crawl entire websites with BFS/DFS traversal.

## Endpoint

```
POST /v1/crawl
```

### Request

```json
{
  "url": "https://example.com",
  "max_pages": 10,
  "max_depth": 2,
  "include_paths": ["/docs/", "/blog/"],
  "exclude_paths": ["/cart/", "/login/"]
}
```

### Response

```json
{
  "success": true,
  "data": {
    "pages": [
      {
        "url": "https://example.com/docs",
        "title": "Documentation",
        "content": "# Docs\n\n...",
        "links": ["https://example.com/docs/api"]
      }
    ],
    "stats": {
      "pages_scraped": 10,
      "pages_failed": 0,
      "elapsed_seconds": 5.2
    }
  }
}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | (required) | Seed URL |
| `max_pages` | integer | `10` | Max pages to scrape |
| `max_depth` | integer | `2` | Max link depth |
| `include_paths` | array | (none) | URL path patterns to include |
| `exclude_paths` | array | (none) | URL path patterns to skip |
