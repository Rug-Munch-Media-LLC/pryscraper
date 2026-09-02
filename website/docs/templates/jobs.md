# Jobs Templates

Job-board and professional-profile templates for recruiting, market
mapping, and salary research.

## Templates

| Template | Site | Fields |
|----------|------|--------|
| `linkedin-job` | linkedin.com | job title, company, location, description |
| `linkedin-profile` | linkedin.com | profile data |
| `indeed-job` | indeed.com | listings |
| `glassdoor-job` | glassdoor.com | listings + company data |
| `monster-job` | monster.com | listings |
| `ziprecruiter-job` | ziprecruiter.com | listings |

## Dedicated MCP tools (beyond templates)

- `pry_jobs_list` — ATS job listings across Greenhouse, Lever, Ashby, and
  Workday ($0.002)
- `pry_jobs_salary` — salary bands from Levels.fyi ($0.002)

## Usage

```bash
# Execute — $0.002 (template_execute)
curl -X POST http://localhost:8002/v1/templates/execute \
  -H "Content-Type: application/json" \
  -d '{"template_id": "indeed-job", "url": "https://indeed.com/viewjob?jk=..."}'
```

Via MCP: `pry_search_templates` (keyword: "job") → `pry_template`.

## Compliance note

Job boards are aggressive with bot detection. Templates route through the
15-tier fallback chain automatically; check `pry_compliance` before
bulk-harvesting listings and respect each board's terms of service.
