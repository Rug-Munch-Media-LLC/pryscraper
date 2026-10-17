"""Pry — markdown normalization + 0-100 quality score (crawl4ai parity).

Keeps absolute links, fenced code, one h1 + ordered headings, GFM tables,
optional images, a noise-free body and deduped paragraphs.
"""

# SPDX-License-Identifier: MIT — part of Pry (https://git.rugmunch.io/RugMunchMedia/pryscraper)

import re
from itertools import pairwise
from typing import Any
from urllib.parse import urljoin

_SKIP = ("http://", "https://", "mailto:", "tel:", "#", "data:", "//")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
_IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
_REL_LINK = re.compile(r"(?<!!)\]\((?!https?://|mailto:|tel:|#|data:|\s*\))")
_NOISE = re.compile(
    r"(?i)^\W{0,4}(menu|navigation|nav|breadcrumbs?|skip to content|"
    r"accept (all )?cookies|cookie (policy|settings)|subscribe|newsletter|"
    r"share( this)?|follow us|advertisement|sponsored|all rights reserved|"
    r"©|copyright)\b"
)
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_LANG_SIGNS = (
    ("python", r"^\s*(?:async )?def |^\s*(?:import|from) \w+ import |^\s*class \w+[:(]"),
    ("js", r"=>|^\s*(?:const|let|function) |console\.log\("),
    ("sql", r"(?i)\b(select|insert into|update|delete from|create table)\b"),
    ("bash", r"^#!|^\s*\$ \w"),
    ("json", r'^\s*[\[{]\s*$|^\s*"[\w-]+"\s*:'),
    ("html", r"^\s*<\w+[^>]*>"),
)
_WEIGHTS = {
    "links": 20,
    "code": 15,
    "headings": 15,
    "tables": 15,
    "images": 5,
    "noise": 15,
    "dedup": 15,
}


def _links(text: str, base: str, include_images: bool) -> str:
    """Absolutize link/image targets, then drop images unless requested."""
    if base:

        def link(m: re.Match[str]) -> str:
            if m.group(2).startswith(_SKIP):
                return m.group(0)
            return f"[{m.group(1)}]({urljoin(base, m.group(2))}{m.group(3) or ''})"

        def img(m: re.Match[str]) -> str:
            target = m.group(2)
            if not target.startswith(_SKIP):
                target = urljoin(base, target)
            return f"![{m.group(1)}]({target}{m.group(3) or ''})"

        text = _IMG.sub(img, _LINK.sub(link, text))
    return text if include_images else _IMG.sub("", text)


def _strip_noise(text: str) -> str:
    """Drop nav/footer/aside blocks and cookie/menu boilerplate lines."""
    text = re.sub(r"(?is)<(nav|footer|aside)\b.*?</\1>", "", text)
    kept = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) < 160 and _NOISE.match(stripped):
            continue
        kept.append(line)
    return "\n".join(kept)


def _tables(text: str) -> str:
    """Convert leftover HTML tables to GFM pipe tables."""
    if "<table" not in text.lower():
        return text
    from bs4 import BeautifulSoup

    def repl(m: re.Match[str]) -> str:
        soup = BeautifulSoup(m.group(0), "html.parser")
        rows = [
            [c.get_text(" ", strip=True).replace("|", "\\|") for c in tr.find_all(["th", "td"])]
            for tr in soup.find_all("tr")
        ]
        rows = [r for r in rows if r]
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        return "\n".join(out + ["| " + " | ".join(r) + " |" for r in rows[1:]])

    return re.sub(r"(?is)<table\b.*?</table>", repl, text)


def _headings(text: str) -> str:
    """Keep the article h1 (last one) and never skip a level."""
    text = re.sub(r"(?m)^([^\n]+)\n=+\s*$", r"# \1", text)  # setext h1 -> ATX
    text = re.sub(r"(?m)^([^\n]+)\n-{2,}\s*$", r"## \1", text)  # setext h2 -> ATX
    lines = text.split("\n")
    h1 = [
        (i, m.group(2))
        for i, ln in enumerate(lines)
        if (m := _HEADING.match(ln)) and m.group(1) == "#"
    ]
    keep = max(h1, key=lambda p: len(p[1]))[0] if len(h1) > 1 else -1
    lines = ["" if i in {p[0] for p in h1} and i != keep else ln for i, ln in enumerate(lines)]
    prev = 0
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if prev and level > prev + 1:
            level = prev + 1
        prev = level
        lines[i] = f"{'#' * level} {m.group(2)}"
    return "\n".join(lines)


def _fences(text: str) -> str:
    """Tag fenced code blocks with a language when the body is recognizable."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("```") or line[3:].strip():
            out.append(line)
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith("```"):
            j += 1
        body = "\n".join(lines[i + 1 : j])
        lang = next((name for name, pat in _LANG_SIGNS if re.search(pat, body, re.M)), "")
        out.append(f"```{lang}" if lang else line)
        out.extend(lines[i + 1 : j])
        if j < len(lines):
            out.append(lines[j])
        i = j + 1
    return "\n".join(out)


def normalize_markdown(content: str, url: str = "", include_images: bool = False) -> str:
    """Apply the seven crawl4ai-parity markdown fixes, then dedup paragraphs."""
    if not content:
        return ""
    text = _links(_tables(_strip_noise(content)), url, include_images)
    text = _fences(_headings(text))
    lines, inside = [], False
    for ln in text.split("\n"):
        if ln.startswith("```"):
            inside = not inside
            lines.append(ln)
        else:
            lines.append(ln if inside else re.sub(r"[ \t]+", " ", ln).rstrip())
    out: list[str] = []
    seen: set[str] = set()
    for block in re.split(r"\n{2,}", "\n".join(lines)):
        block = block.strip()
        key = re.sub(r"\s+", " ", block).lower()
        if not block or (len(key) > 10 and key in seen):
            continue
        seen.add(key)
        out.append(block)
    return "\n\n".join(out)


def _fence_langs(text: str) -> list[str]:
    langs: list[str] = []
    inside, cur = False, ""
    for line in text.split("\n"):
        if not line.startswith("```"):
            continue
        if inside:
            langs.append(cur)
        inside, cur = not inside, line[3:].strip()
    return langs


def _check_headings(levels: list[int]) -> float:
    if levels.count(1) > 1:
        return 0.0
    return 0.5 if any(b > a + 1 for a, b in pairwise(levels)) else 1.0


def _check_images(text: str, include_images: bool) -> float:
    if include_images:
        return 0.0 if re.search(r"!\[\]\((?!https?://)", text) else 1.0
    return 0.0 if "![" in text else 1.0


def _check_noise(lines: list[str]) -> float:
    if not lines:
        return 1.0
    ratio = sum(1 for ln in lines if _NOISE.match(ln)) / len(lines)
    return max(0.0, 1.0 - ratio * 5)


def _check_dedup(text: str, blocks: list[str]) -> float:
    return 0.0 if "\n\n\n" in text or len(blocks) != len(set(blocks)) else 1.0


def markdown_quality(content: str, url: str = "", include_images: bool = False) -> dict[str, Any]:
    """Score markdown 0-100 against the same seven checks (weighted)."""
    text = content or ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    blocks = [re.sub(r"\s+", " ", b).lower() for b in re.split(r"\n{2,}", text) if b.strip()]
    levels = [len(m.group(1)) for m in (_HEADING.match(ln) for ln in text.split("\n")) if m]
    langs = _fence_langs(text)
    checks = {
        "links": 0.0 if _REL_LINK.search(text) else 1.0,
        "code": (sum(1 for lang in langs if lang) / len(langs)) if langs else 1.0,
        "headings": _check_headings(levels),
        "tables": 0.0 if "<table" in text.lower() else 1.0,
        "images": _check_images(text, include_images),
        "noise": _check_noise(lines),
        "dedup": _check_dedup(text, blocks),
    }
    score = sum(_WEIGHTS[name] * value for name, value in checks.items())
    return {"score": round(score), "checks": {k: round(v, 3) for k, v in checks.items()}}


def finalize_markdown(result: dict[str, Any], url: str = "", include_images: bool = False) -> dict:
    """Normalize ``result["content"]`` and attach the quality metadata."""
    content = normalize_markdown(result.get("content", ""), url, include_images)
    quality = markdown_quality(content, url, include_images)
    result["content"] = content[:5_000_000]
    result["markdown_quality"] = quality["score"]
    result["metadata"] = {
        "markdown_quality": quality["score"],
        "markdown_checks": quality["checks"],
    }
    return result
