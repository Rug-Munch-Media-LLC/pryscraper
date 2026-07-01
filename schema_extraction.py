"""Pry — Schema.org / JSON-LD Auto-Extraction.
Most modern sites (e-commerce, news, recipes, events) embed structured data
as JSON-LD in <script type=\"application/ld+json\"> tags. Extract this directly
instead of parsing HTML — 100x faster and more accurate."""

import json
import logging
import re
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class SchemaExtractor:
    """Extract structured data from Schema.org / JSON-LD / Microdata / RDFa."""

    SCHEMA_TYPES: ClassVar[dict[str, list[str]]] = {
        "Product": ["name", "description", "brand", "sku", "mpn", "image", "offers"],
        "Article": ["headline", "author", "datePublished", "image", "publisher"],
        "NewsArticle": ["headline", "author", "datePublished", "articleBody"],
        "Recipe": ["name", "recipeIngredient", "recipeInstructions", "cookTime"],
        "Event": ["name", "startDate", "endDate", "location", "offers"],
        "Organization": ["name", "url", "logo", "address", "contactPoint"],
        "Person": ["name", "jobTitle", "worksFor", "sameAs"],
        "LocalBusiness": ["name", "address", "telephone", "openingHours", "priceRange"],
        "Review": ["author", "datePublished", "reviewBody", "reviewRating"],
        "VideoObject": ["name", "description", "thumbnailUrl", "uploadDate", "duration"],
    }

    _JSONLD_RE = re.compile(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )

    def extract_jsonld(self, html: str) -> list[dict[str, Any]]:
        """Extract all JSON-LD blocks from HTML."""
        results: list[dict[str, Any]] = []
        for match in self._JSONLD_RE.finditer(html):
            raw = match.group(1)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                cleaned = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
                try:
                    data = json.loads(cleaned)
                except (json.JSONDecodeError, ValueError):
                    logger.debug("jsonld_parse_failed", extra={"snippet": raw[:80]})
                    continue
            if isinstance(data, list):
                results.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    results.extend(d for d in data["@graph"] if isinstance(d, dict))
                else:
                    results.append(data)
        return results

    def extract_microdata(self, html: str) -> list[dict[str, Any]]:
        """Extract Microdata from HTML (itemtype, itemprop)."""
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html)
        results: list[dict[str, Any]] = []
        for elem in tree.xpath('//*[@itemtype]'):
            itemtype = elem.get("itemtype") or ""
            item: dict[str, Any] = {"@type": itemtype.split("/")[-1]}
            for prop in elem.xpath('.//*[@itemprop]'):
                key = prop.get("itemprop")
                if not key:
                    continue
                value = (
                    prop.get("content")
                    or prop.get("href")
                    or (prop.text_content().strip() if prop.text_content() else "")
                )
                if value:
                    item[key] = value
            results.append(item)
        return results

    def extract_rdfa(self, html: str) -> list[dict[str, Any]]:
        """Extract RDFa attributes from HTML."""
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html)
        results: list[dict[str, Any]] = []
        for elem in tree.xpath('//*[@typeof]'):
            item: dict[str, Any] = {"@type": elem.get("typeof")}
            for prop in elem.xpath('.//*[@property]'):
                raw_key = prop.get("property") or ""
                key = raw_key.split(":")[-1]
                value = prop.get("content") or prop.text_content().strip()
                if key and value:
                    item[key] = value
            results.append(item)
        return results

    def extract_all(self, html: str) -> dict[str, Any]:
        """Extract all structured data from HTML."""
        jsonld = self.extract_jsonld(html)
        microdata = self.extract_microdata(html)
        rdfa = self.extract_rdfa(html)
        normalized = [self._normalize(item) for item in jsonld + microdata + rdfa]
        return {
            "jsonld": jsonld,
            "microdata": microdata,
            "rdfa": rdfa,
            "normalized": normalized,
            "count": len(normalized),
        }

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any]:
        """Normalize schema item to common format."""
        schema_type = item.get("@type", item.get("type", "Unknown"))
        if "@context" in item:
            source = "jsonld"
        elif "itemtype" in str(item) or any(
            isinstance(v, str) and v.startswith("https://schema.org/") for v in item.values()
        ):
            source = "microdata"
        elif "typeof" in str(item):
            source = "rdfa"
        else:
            source = "unknown"
        return {
            "type": schema_type,
            "source": source,
            "data": {
                k: v
                for k, v in item.items()
                if k not in ("@context", "itemtype", "typeof", "itemprop", "property")
            },
        }
