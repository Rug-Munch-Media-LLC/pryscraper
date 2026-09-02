# Legal Templates

Legal and public-record extraction templates, plus the dedicated legal MCP
tool family.

## Templates

| Template | Site | Fields |
|----------|------|--------|
| `google-patent` | patents.google.com | patent title, abstract, claims, assignee |
| `uspto-patent` | uspto.gov | USPTO patent data |
| `wikipedia-article` | wikipedia.org | article content, references |

## Dedicated MCP tools (beyond templates)

| Tool | Source | Price |
|------|--------|:-----:|
| `pry_legal_dockets` | CourtListener — U.S. court dockets | $0.005 |
| `pry_legal_sec` | SEC EDGAR — filings, insider trades | $0.005 |
| `pry_legal_sanctions` | OFAC SDN — sanctions name screening | $0.002 |
| `pry_patents` | USPTO patent search | $0.005 |
| `pry_trademarks` | USPTO trademark search | $0.005 |

## Usage

```bash
# Template execution — $0.002
curl -X POST http://localhost:8002/v1/templates/execute \
  -H "Content-Type: application/json" \
  -d '{"template_id": "google-patent", "url": "https://patents.google.com/patent/US..."}'
```

Via MCP: `pry_search_templates` → `pry_template`, or call the dedicated
legal tools directly for structured search APIs.

## Use cases

- Litigation research and docket monitoring
- Counterparty sanctions screening (OFAC SDN)
- Prior-art and IP landscape research
- SEC filing and insider-trade surveillance
