"""Pry — One-file config system.
Define all your scraping jobs in a pry.yml file, run them with `pry run`.

Example pry.yml:
```yaml
jobs:
  - name: product_prices
    url: https://store.com/products
    schedule: every 1h
    extract:
      title: "h1.product-name"
      price: ".price"
      stock: ".stock-status"
    output: csv
    webhook: slack://C012345
```

"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import os

import yaml


class Pryfile:
    """Parse and execute pry.yml job definitions."""

    def __init__(self, path: str = "pry.yml"):
        self.path = path
        self.jobs = []
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            # Try pry.yaml, Pryfile, pryfile.yml
            for alt in ["pry.yaml", "Pryfile", "pryfile.yml", "pryfile.yaml"]:
                if os.path.exists(alt):
                    self.path = alt
                    break
            else:
                return  # No config file found — that's OK for CLI usage
        with open(self.path) as f:
            data = yaml.safe_load(f)
        self.jobs = data.get("jobs", []) if data else []
        self.global_settings = {k: v for k, v in (data or {}).items() if k != "jobs"}

    async def run_all(self, scraper=None) -> list[dict]:
        """Execute all jobs defined in pry.yml. Returns results."""
        from scraper import PryScraper

        s = scraper or PryScraper()
        results = []
        for job in self.jobs:
            try:
                result = await self._run_job(job, s)
                results.append(result)
            except Exception as e:
                results.append({"name": job.get("name", "unknown"), "error": str(e)})
        return results

    async def _run_job(self, job: dict, scraper) -> dict:
        name = job.get("name", "unnamed")
        url = job.get("url", "")
        if not url:
            return {"name": name, "error": "No URL specified"}

        scrape_result = await scraper.scrape(
            url,
            {
                "timeout": job.get("timeout", 30),
                "bypass_cloudflare": job.get("bypass_cloudflare", True),
            },
        )

        result = {
            "name": name,
            "url": url,
            "status": scrape_result.get("status"),
            "method": scrape_result.get("method", "unknown"),
            "content_length": len(scrape_result.get("content", "")),
        }

        # Extract structured fields if defined
        extract_schema = job.get("extract", {})
        if extract_schema:
            from extractor import SchemaExtractor

            ex = SchemaExtractor()
            extracted = ex._pattern_extract(scrape_result.get("content", ""), extract_schema)
            result["extracted"] = extracted

        # Transform output if specified
        output_format = job.get("output", self.global_settings.get("output", "json"))
        if output_format == "csv" and "extracted" in result:
            import csv
            import io

            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=result["extracted"].keys())
            w.writeheader()
            w.writerow(result["extracted"])
            result["output"] = buf.getvalue()
        elif output_format == "json":
            result["output"] = json.dumps(result.get("extracted", {}), indent=2)

        return result

    def list_jobs(self) -> list[dict]:
        """List all configured jobs without executing them."""
        return [
            {
                "name": j.get("name"),
                "url": j.get("url"),
                "schedule": j.get("schedule", "manual"),
                "output": j.get("output", "json"),
            }
            for j in self.jobs
        ]
