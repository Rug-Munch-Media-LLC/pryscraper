# Pry — FAQ

**What is Pry?** A multi-source crypto intelligence crawler framework: async pipeline, pluggable sources, normalized output (pryscraper.com).

**What can it scrape?** Any HTTP/JSON source via source plugins; ships with crypto-market connectors. Respect each source's ToS and rate limits — the framework enforces configurable backoff.

**How do I add a source?** Drop a connector module under the sources package, declare its schedule + parser, add a test. See CONTRIBUTING.md.

**Does it need a database?** Optional — results emit to stdout/files by default; Postgres sink available for production pipelines.

**How do I avoid getting rate-limited?** Configure per-source concurrency + backoff in config. Free-first ordering: free endpoints are preferred automatically.

**Python version?** 3.11+. Fully async (httpx.AsyncClient).

**Is scraping legal?** Pry is a tool; you are responsible for complying with target sites' terms and applicable law.
