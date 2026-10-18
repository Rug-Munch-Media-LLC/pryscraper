"""HTML table parsing for schema extraction.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from typing import Any


def _headers(rows: list[Any]) -> list[str]:
    cells = rows[0].xpath("./th|./td")
    return [c.text_content().strip() or f"col_{i}" for i, c in enumerate(cells)]


def _row_values(row: Any) -> list[str]:
    return [c.text_content().strip() for c in row.xpath("./td|./th")]


def parse_table(html: str, selector: str) -> list[dict[str, str]]:
    """Parse the first matching HTML table into row dicts.

    Pure function (no fetch): returns ``[]`` when the table or its rows are
    absent. Raises only if the selector is malformed; callers guard that.
    """
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html)
    tables = tree.cssselect(selector) if selector != "table" else tree.xpath("//table")
    if not tables:
        return []
    rows = tables[0].xpath(".//tr")
    if not rows:
        return []
    headers = _headers(rows)
    out: list[dict[str, str]] = []
    for row in rows[1:]:
        values = _row_values(row)
        if not values:
            continue
        out.append(
            {headers[i] if i < len(headers) else f"col_{i}": v for i, v in enumerate(values)}
        )
    return out


__all__ = ["parse_table"]
