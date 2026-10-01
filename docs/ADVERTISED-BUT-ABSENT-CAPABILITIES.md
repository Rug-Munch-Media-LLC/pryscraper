# Advertised-but-absent MCP capabilities (2026-10-01)

**Status: historical record. The endpoints were never built. Do not re-add the
tool entries without the endpoint.**

The MCP surface advertised tools that had no execution path anywhere. Two
independent failure modes produced the same user-visible result (an LLM reads
the description, calls the tool, gets an error, then invents a workaround):

1. **No local executor and no REST route** — the tool fell through to the REST
   proxy, which called a path absent from the API contract and returned `404`.
2. **Local dispatcher existed but could never import its module** — the tool
   returned `MODULE_UNAVAILABLE` and never fell through to REST, so its route
   was unreachable even where one existed.

`tests/test_mcp_tool_route_drift.py` now asserts every `TOOL_ROUTES` target
resolves against `pry.api.app_factory.app.openapi()["paths"]`. Use that test,
not the table below, as the authority on what is wired.

## Removed tools — no local executor, no REST route (14)

| Tool | Dead REST route | Origin commit |
|------|-----------------|---------------|
| `pry_search` | `POST /v1/search` | `31b19aa7` |
| `pry_search_web` | `GET /v1/search` | `31b19aa7` |
| `pry_search_extract` | `POST /v1/search/extract` | `31b19aa7` |
| `pry_scrape_with_actions` | `POST /v1/scrape/actions` | `31b19aa7` |
| `pry_map_site` | `POST /v1/site/map` | `662d10eb` |
| `pry_crawl_to_markdown` | `POST /v1/site/crawl` | `662d10eb` |
| `pry_crawl_for_rag` | `POST /v1/site/rag` | `662d10eb` |
| `pry_extract_schema` | `POST /v1/extract/schema` | `662d10eb` |
| `pry_extract_batch` | `POST /v1/extract/batch` | `662d10eb` |
| `pry_extract_prompt` | `POST /v1/extract/prompt` | `662d10eb` |
| `pry_adaptive_scrape` | `POST /v1/scrape/adaptive` | `662d10eb` |
| `pry_filter_content` | `POST /v1/content/filter` | `662d10eb` |
| `pry_extract_main` | `POST /v1/content/extract-main` | `662d10eb` |
| `pry_chunk_for_rag` | `POST /v1/content/chunk` | `662d10eb` |

`/v1/search` was a Firecrawl-scale web-search product. It appeared in exactly two
places in the repo: the `TOOL_ROUTES` table above, and a docstring in
`src/pry/api/routers/core/well_known.py:90`. It was never a route.

Note that `pry/engine/` still ships much of the underlying machinery
(`markdown_gen.py`, `content_filter.py`, `adaptive.py`, `actions.py`). That code
is reachable from the REST API and the Python SDK; it was never wired to an MCP
tool. **Re-adding a tool entry requires an endpoint in the OpenAPI contract, or
a dispatcher registered in `ToolRegistry` that actually resolves.**

## Repaired rather than removed (1)

`pry_mega_search` (`pry/engine/mega_search.py`) had a complete, working engine
and a complete dispatcher — `call_mega_search_tool` — that was simply never
registered in `ToolRegistry._DOMAIN_DISPATCHERS`, so it fell through to the
non-existent `/v1/search`. It is now registered and executes locally.

## Kept, still not usable through MCP (3)

These have real routers (all return `402 Payment Required` from `TestClient`,
i.e. the route exists) and their backing code imports cleanly. They stay because
the capability is real and the gap is a wiring bug, not a missing feature. Two
distinct blockers apply:

- **`pry_weather`** — route is `GET /v1/climate/forecast`, not
  `GET /v1/climate/weather`.
- **`pry_resale`** — route is `GET /v1/events/{event_id}/resale`.
- **`pry_restaurant`** — route is `GET /v1/food/restaurant/{name}`.

Blocker A (module path): the dispatchers import `{package}.{module}` while the
routers import `datasets.{package}.{module}` — see
`pry_mcp/tools/_common.py:167` vs `src/pry/api/routers/data/food_data.py:45`.
The `datasets.*` packages exist and import fine; the un-prefixed import can
never succeed, so the guarded dispatcher always returns `MODULE_UNAVAILABLE`
and never reaches REST.

Blocker B (path params): `pry_mcp/fallback_server.py` builds proxy URLs by
concatenation (`f"{self.base_url}{path}"`) and never substitutes `{param}`
segments. Even with Blocker A fixed, these detail routes cannot be reached
through the proxy without path templating.

The same Blocker A defect affects 12 further data-domain tools that were dropped
from `TOOL_ROUTES` as unreachable (`pry_app_reviews`, `pry_company_watch`,
`pry_domain`, `pry_firmographics`, `pry_imports`, `pry_jobs_salary`,
`pry_legal_sanctions`, `pry_patents`, `pry_procurement`, `pry_recalls`,
`pry_reviews`, `pry_trademarks`). Their route entries pointed at collection
paths while the real endpoints are detail paths (`/v1/jobs/salary/{company}`,
`/v1/ip/patents/{patent_id}`, `/v1/gov/procurement/{notice_id}`, …) — i.e.
Blocker B as well. The tools remain advertised and remain stubbed.

**Neither blocker was fixed in the drift-cleanup commit.** They are separate
defects requiring path templating in the proxy and a module-path fix in the
dispatchers.
