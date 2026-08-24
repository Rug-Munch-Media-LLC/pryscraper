"""Pry — WebSocket streaming, scheduler, batch-file, recorder, transforms.
New capabilities that make Pry unbeatable."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import csv
import io
import json
from datetime import UTC, datetime
from typing import Any


class StreamManager:
    """Manages WebSocket connections for real-time data streaming."""

    def __init__(self):
        self._connections: dict[str, set] = {}

    def register(self, job_id: str, websocket):
        if job_id not in self._connections:
            self._connections[job_id] = set()
        self._connections[job_id].add(websocket)

    def unregister(self, job_id: str, websocket):
        self._connections.get(job_id, set()).discard(websocket)

    async def broadcast(self, job_id: str, data: dict):
        for ws in self._connections.get(job_id, set()).copy():
            try:
                await ws.send_json(data)
            except Exception:  # noqa: BLE001
                self._connections.get(job_id, set()).discard(ws)


streams = StreamManager()


class BatchProcessor:
    """Process URLs from a file with a template selector."""

    async def from_file(
        self, filepath: str, template: dict, timeout_s: int = 30, max_urls: int = 1000
    ) -> list[dict]:
        from pry.engine.scraper import PryScraper

        s = PryScraper()

        # Read URLs from file (one per line) off the event loop — file may be large.
        def _read_urls(path: str) -> list[str]:
            with open(path) as f:
                return [line.strip() for line in f if line.strip() and not line.startswith("#")]

        urls = await asyncio.to_thread(_read_urls, filepath)
        urls = urls[:max_urls]
        from pry.engine.extractor import SchemaExtractor

        ex = SchemaExtractor()
        results = []

        for i, url in enumerate(urls):
            try:
                result = await s.scrape(url, {"timeout": timeout_s})
                if result.get("status") == "ok":
                    extracted = ex._pattern_extract(result.get("content", ""), template)
                    results.append({"url": url, "status": "ok", "data": extracted})
                else:
                    results.append({"url": url, "status": "error", "error": result.get("error")})
            except OSError as e:
                results.append({"url": url, "status": "error", "error": str(e)})

            # Progress update every 50 URLs
            if (i + 1) % 50 == 0:
                await streams.broadcast(
                    "batch", {"progress": f"{i + 1}/{len(urls)}", "results": len(results)}
                )

        return results


class Recorder:
    """Record browser interactions and export as automation scripts."""

    def __init__(self):
        self._recordings: dict[str, list[dict]] = {}

    def start(self, session_id: str):
        self._recordings[session_id] = []

    def record(self, session_id: str, action: str, selector: str = "", value: str = ""):
        if session_id not in self._recordings:
            self._recordings[session_id] = []
        self._recordings[session_id].append(
            {
                "action": action,
                "selector": selector,
                "value": value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def export(self, session_id: str, fmt: str = "json") -> Any:
        steps = self._recordings.get(session_id, [])
        if fmt == "json":
            return json.dumps(steps, indent=2)
        elif fmt == "yaml":
            lines = ["steps:"]
            for s in steps:
                lines.append(f"  - action: {s['action']}")
                if s.get("selector"):
                    lines.append(f'    selector: "{s["selector"]}"')
                if s.get("value"):
                    lines.append(f'    value: "{s["value"]}"')
            return "\n".join(lines)
        elif fmt == "pry":
            # Generate pry.yml compatible output
            return {"steps": steps}
        return steps

    def clear(self, session_id: str):
        self._recordings.pop(session_id, None)


recorder = Recorder()


class TransformEngine:
    """Transform scraped data into multiple output formats."""

    @staticmethod
    def to_sql(data: dict, table: str = "scraped_data") -> str:
        """Convert scraped data to SQL INSERT statement."""
        columns = list(data.keys())
        values = []
        for v in data.values():
            if isinstance(v, str):
                escaped = v.replace("'", "''")
                values.append(f"'{escaped}'")
            elif v is None:
                values.append("NULL")
            else:
                values.append(str(v))
        cols = ", ".join(columns)
        vals = ", ".join(values)
        return f"INSERT INTO {table} ({cols}) VALUES ({vals});"  # noqa: S608 - table is caller-supplied const, values escaped above

    @staticmethod
    def to_csv(data: list[dict]) -> str:
        """Convert list of dicts to CSV string."""
        if not data:
            return ""
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=data[0].keys())
        w.writeheader()
        w.writerows(data)
        return buf.getvalue()

    @staticmethod
    def to_html_table(data: list[dict]) -> str:
        """Convert list of dicts to HTML table."""
        if not data:
            return "<table></table>"
        cols = data[0].keys()
        rows = "\n".join(
            f"    <tr>{''.join(f'<td>{v}</td>' for v in row.values())}</tr>" for row in data
        )
        return f"<table>\n  <tr>{''.join(f'<th>{c}</th>' for c in cols)}</tr>\n{rows}\n</table>"

    @staticmethod
    def to_markdown_table(data: list[dict]) -> str:
        if not data:
            return ""
        cols = list(data[0].keys())
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join(["---"] * len(cols)) + " |"
        rows = "\n".join("| " + " | ".join(str(v) for v in row.values()) + " |" for row in data)
        return f"{header}\n{sep}\n{rows}"
