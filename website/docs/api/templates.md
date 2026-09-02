# Templates

Pry ships **110 pre-built scraper templates** — one-click extractors for
popular websites (Amazon, Walmart, Target, Best Buy, LinkedIn, Indeed,
GitHub, news sites, and more). Each template declares CSS selectors and
field types, so extraction is deterministic and cheap (no LLM needed).

## Browse the catalog

```bash
# List all templates (free)
curl http://localhost:8002/v1/templates

# Get one template's full schema (free)
curl http://localhost:8002/v1/templates/amazon-product
```

## Execute a template

```bash
# Single execution — $0.002 (template_execute)
curl -X POST http://localhost:8002/v1/templates/execute \
  -H "Content-Type: application/json" \
  -d '{"template_id": "amazon-product", "url": "https://amazon.com/dp/B0..."}'

# Batch — up to 20 URLs, $0.01 (template_batch_execute)
curl -X POST http://localhost:8002/v1/templates/batch \
  -H "Content-Type: application/json" \
  -d '{"template_id": "amazon-product", "urls": ["https://..."]}'
```

## Via MCP

- `pry_search_templates` — search the catalog by keyword, category, or site
  name (free listing)
- `pry_template` — execute a template (`template_execute`, $0.002)

## Categories

The catalog spans ecommerce (largest group), news, professional, travel,
financial, reviews, reference, social, classifieds, business, media,
content, real estate, sports, development, and local. See the dedicated
pages for [ecommerce](../templates/ecommerce),
[jobs](../templates/jobs), and [legal](../templates/legal) highlights.

## Pricing

| Endpoint | Operation | Price |
|----------|-----------|:-----:|
| `GET /v1/templates` | — | free |
| `GET /v1/templates/{id}` | — | free |
| `POST /v1/templates/execute` | `template_execute` | $0.002 |
| `POST /v1/templates/batch` | `template_batch_execute` | $0.01 |
