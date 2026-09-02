# Ecommerce Templates

The largest template group: **43 ecommerce templates** for product and
search extraction across major retailers and marketplaces.

## Marketplace highlights

| Template | Site | Fields |
|----------|------|--------|
| `amazon-product` | amazon.com | title, price, rating, reviews, images, availability |
| `amazon-search` | amazon.com | search results grid |
| `ebay-listing` | ebay.com | listing details |
| `walmart-product` | walmart.com | product data |
| `etsy-product` | etsy.com | handmade/marketplace listings |
| `aliexpress-product` | aliexpress.com | cross-border listings |
| `bestbuy-product` | bestbuy.com | electronics |
| `target-product` | target.com | general retail |
| `costco-product` | costco.com | warehouse club |
| `adidas-product` / `asos-product` / `gap-product` | fashion | apparel data |

Also included: `bhphotovideo-product`, `chewy-product` (pet),
`crate-and-barrel-product` (home), `cvs-product` (pharmacy/retail),
`dicks-sporting-goods`, and more — run
`GET /v1/templates` for the full list.

## Usage

```bash
# Execute — $0.002 (template_execute)
curl -X POST http://localhost:8002/v1/templates/execute \
  -H "Content-Type: application/json" \
  -d '{"template_id": "amazon-product", "url": "https://amazon.com/dp/B0..."}'
```

Via MCP: `pry_search_templates` (category filter) → `pry_template`.

## When to use a template vs `pry_extract`

- **Template exists** → use it: deterministic selectors, $0.002, no LLM.
- **No template** → `pry_extract` with CSS selectors ($0.005), or
  `pry_scrape` + LLM for unstructured pages.
