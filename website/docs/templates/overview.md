# Templates

110+ pre-built scraper templates for common websites.

## Categories

### Ecommerce
- Amazon product/search
- Walmart product
- eBay listings
- Shopify stores
- Etsy products

### Jobs
- LinkedIn jobs
- Indeed
- Glassdoor
- Greenhouse/Lever/ATS boards

### Legal
- Court dockets (CourtListener)
- SEC EDGAR
- OFAC sanctions

### Real Estate
- Zillow/Redfin search
- Realtor.com

### Data
- News search
- Weather
- Academic papers
- Company data

## Usage

```bash
# Search templates
pry search_templates --category ecommerce

# Execute template
pry template --name amazon_product --url "https://amazon.com/dp/B08N5WRWNW"
```

## MCP

```json
{
  "method": "tools/call",
  "params": {
    "name": "pry_template",
    "arguments": {
      "template_name": "amazon_product",
      "url": "https://amazon.com/dp/B08N5WRWNW"
    }
  }
}
```
