# Extract API

Extract structured data from URLs using CSS selectors or LLM.

## Endpoint

```
POST /v1/extract
```

### CSS Selectors (10x cheaper than LLM)

```json
{
  "url": "https://example.com/products",
  "extract_schema": {
    "fields": [
      {"name": "title", "selector": "h1", "type": "string"},
      {"name": "price", "selector": ".price", "type": "number"},
      {"name": "image", "selector": "img.product", "type": "string", "attribute": "src"},
      {"name": "availability", "selector": ".stock", "type": "string"}
    ]
  }
}
```

### LLM Extraction (expensive, handles unstructured data)

```json
{
  "url": "https://example.com/article",
  "extract_mode": "llm",
  "extract_prompt": "Extract the article title, author, date, and summary"
}
```

### Response

```json
{
  "success": true,
  "data": {
    "url": "https://example.com/products",
    "extracted": [
      {"title": "Product A", "price": 29.99, "image": "...", "availability": "In Stock"},
      {"title": "Product B", "price": 49.99, "image": "...", "availability": "Out of Stock"}
    ]
  }
}
```
