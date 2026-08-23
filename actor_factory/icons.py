"""Pry - Apify Actor Factory: programmatic icon generation.

Every generated actor ships a distinctive ``icon.svg`` ready for Apify
Console's Display-information upload - zero manual design work. Icons are
deterministic per spec: category color + glyph shape + actor initial.

Design language: rounded-square tile, two-tone gradient in the category
hue, white geometric glyph, subtle inner highlight. Renders crisply at
16px favicon through 256px store card.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import hashlib
from typing import Any

# Category -> (primary hue, secondary hue) HSL triples for gradients.
CATEGORY_COLORS: dict[str, tuple[int, int]] = {
    "SCRAPER": (88, 60),  # lime family (Pry brand)
    "CRAWLER": (150, 120),  # green
    "MONITOR": (32, 12),  # orange
    "E_COMMERCE": (42, 22),  # amber
    "SEO": (210, 190),  # blue
    "LEAD_GENERATION": (142, 122),  # emerald
    "COMPLIANCE": (0, 340),  # red/rose
    "LEGAL": (222, 205),  # slate blue
    "GOV": (245, 225),  # indigo
    "CRYPTO": (270, 250),  # violet
    "TRAVEL": (190, 170),  # cyan
    "HEALTHCARE": (172, 152),  # teal
    "AI": (285, 265),  # purple
}

# Glyph library: simple white-on-color SVG paths keyed by concept.
_GLYPHS: dict[str, str] = {
    # magnifier (scrape/search/serp/rank)
    "search": '<circle cx="90" cy="90" r="34" fill="none" stroke="#fff" stroke-width="11"/><line x1="116" y1="116" x2="146" y2="146" stroke="#fff" stroke-width="13" stroke-linecap="round"/>',
    # web/spider (crawl/harvest/backlinks)
    "web": '<circle cx="128" cy="128" r="56" fill="none" stroke="#fff" stroke-width="7"/><circle cx="128" cy="128" r="30" fill="none" stroke="#fff" stroke-width="6"/><line x1="72" y1="128" x2="184" y2="128" stroke="#fff" stroke-width="6"/><line x1="128" y1="72" x2="128" y2="184" stroke="#fff" stroke-width="6"/><line x1="88" y1="88" x2="168" y2="168" stroke="#fff" stroke-width="5"/><line x1="168" y1="88" x2="88" y2="168" stroke="#fff" stroke-width="5"/>',
    # camera (screenshot/vision)
    "camera": '<rect x="66" y="96" width="124" height="84" rx="14" fill="#fff"/><path d="M108 96 L118 78 L138 78 L148 96 Z" fill="#fff"/><circle cx="128" cy="136" r="24" fill="{bg}"/>',
    # pulse (monitor/watch/alert)
    "pulse": '<polyline points="64,140 100,140 114,96 134,164 150,120 192,120" fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>',
    # document (parser/corpus/blog/newsletter)
    "document": '<path d="M84 56 L148 56 L176 88 L176 200 L84 200 Z" fill="#fff"/><path d="M148 56 L148 88 L176 88" fill="none" stroke="{bg}" stroke-width="6"/><line x1="100" y1="112" x2="160" y2="112" stroke="{bg}" stroke-width="8" stroke-linecap="round"/><line x1="100" y1="140" x2="160" y2="140" stroke="{bg}" stroke-width="8" stroke-linecap="round"/><line x1="100" y1="168" x2="140" y2="168" stroke="{bg}" stroke-width="8" stroke-linecap="round"/>',
    # tag/price (price/deals/inventory)
    "tag": '<path d="M70 70 L142 70 L186 114 L128 186 L70 128 Z" fill="#fff"/><circle cx="98" cy="98" r="14" fill="{bg}"/>',
    # shield (compliance/security/gdpr)
    "shield": '<path d="M128 52 L188 76 L188 132 C188 168 160 192 128 204 C96 192 68 168 68 132 L68 76 Z" fill="#fff"/><path d="M104 130 L122 148 L156 110" fill="none" stroke="{bg}" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>',
    # scales (legal/court)
    "scales": '<line x1="128" y1="64" x2="128" y2="180" stroke="#fff" stroke-width="10"/><line x1="80" y1="80" x2="176" y2="80" stroke="#fff" stroke-width="10"/><path d="M56 128 A24 24 0 0 0 104 128 Z" fill="#fff"/><path d="M152 128 A24 24 0 0 0 200 128 Z" fill="#fff"/><line x1="104" y1="188" x2="152" y2="188" stroke="#fff" stroke-width="10" stroke-linecap="round"/>',
    # globe (travel/maps/local)
    "globe": '<circle cx="128" cy="128" r="58" fill="none" stroke="#fff" stroke-width="9"/><ellipse cx="128" cy="128" rx="26" ry="58" fill="none" stroke="#fff" stroke-width="7"/><line x1="70" y1="128" x2="186" y2="128" stroke="#fff" stroke-width="7"/><path d="M82 92 A70 70 0 0 1 174 92" fill="none" stroke="#fff" stroke-width="6"/><path d="M82 164 A70 70 0 0 0 174 164" fill="none" stroke="#fff" stroke-width="6"/>',
    # plane (travel/flights)
    "plane": '<path d="M40 140 L200 96 L216 116 L120 168 L128 196 L108 200 L92 164 L48 156 Z" fill="#fff"/>',
    # heart-pulse (healthcare/trials)
    "health": '<path d="M128 188 C70 150 52 116 52 92 C52 68 70 52 92 52 C106 52 120 60 128 74 C136 60 150 52 164 52 C186 52 204 68 204 92 C204 116 186 150 128 188 Z" fill="#fff"/><polyline points="96,120 118,120 126,102 138,138 148,120 162,120" fill="none" stroke="{bg}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>',
    # building (gov/tender/directory)
    "building": '<rect x="76" y="72" width="104" height="128" fill="#fff"/><rect x="60" y="56" width="136" height="18" fill="#fff"/><g fill="{bg}"><rect x="92" y="104" width="20" height="20"/><rect x="144" y="104" width="20" height="20"/><rect x="92" y="140" width="20" height="20"/><rect x="144" y="140" width="20" height="20"/></g>',
    # coin (crypto/token)
    "coin": '<circle cx="128" cy="128" r="62" fill="#fff"/><circle cx="128" cy="128" r="46" fill="none" stroke="{bg}" stroke-width="7"/><text x="128" y="148" font-family="monospace" font-size="56" font-weight="bold" fill="{bg}" text-anchor="middle">P</text>',
    # rss waves (podcast/newsletter/feed)
    "rss": '<circle cx="86" cy="170" r="16" fill="#fff"/><path d="M70 108 A58 58 0 0 1 128 166" fill="none" stroke="#fff" stroke-width="16" stroke-linecap="round"/><path d="M70 60 A108 108 0 0 1 178 168" fill="none" stroke="#fff" stroke-width="16" stroke-linecap="round"/>',
    # link (backlinks/seo)
    "link": '<path d="M108 148 L84 172 C68 188 44 188 32 172 C16 156 16 132 32 116 L56 92" fill="none" stroke="#fff" stroke-width="15" stroke-linecap="round"/><path d="M148 108 L172 84 C188 68 212 68 224 84 C240 100 240 124 224 140 L200 164" fill="none" stroke="#fff" stroke-width="15" stroke-linecap="round"/><line x1="112" y1="144" x2="144" y2="112" stroke="#fff" stroke-width="15" stroke-linecap="round"/>',
    # bug/shield-scan (security scanning)
    "scan": '<rect x="60" y="60" width="136" height="136" rx="20" fill="none" stroke="#fff" stroke-width="10"/><line x1="128" y1="88" x2="128" y2="128" stroke="#fff" stroke-width="12" stroke-linecap="round"/><circle cx="128" cy="158" r="9" fill="#fff"/>',
    # graduation cap (education/scholarship)
    "edu": '<path d="M128 68 L208 104 L128 140 L48 104 Z" fill="#fff"/><path d="M88 122 L88 160 C88 174 168 174 168 160 L168 122" fill="none" stroke="#fff" stroke-width="10"/><line x1="196" y1="112" x2="196" y2="164" stroke="#fff" stroke-width="8" stroke-linecap="round"/>',
    # chat (forums/discussions)
    "chat": '<path d="M64 72 L192 72 C202 72 208 80 208 90 L208 146 C208 156 202 164 192 164 L140 164 L104 196 L104 164 L64 164 C54 164 48 156 48 146 L48 90 C48 80 54 72 64 72 Z" fill="#fff"/><g fill="{bg}"><circle cx="96" cy="118" r="9"/><circle cx="128" cy="118" r="9"/><circle cx="160" cy="118" r="9"/></g>',
    # chart (economics/analytics)
    "chart": '<rect x="72" y="128" width="26" height="60" fill="#fff"/><rect x="115" y="100" width="26" height="88" fill="#fff"/><rect x="158" y="72" width="26" height="116" fill="#fff"/>',
    # database (data collection)
    "database": '<ellipse cx="128" cy="84" rx="56" ry="20" fill="#fff"/><path d="M72 84 L72 172 C72 186 184 186 184 172 L184 84" fill="none" stroke="#fff" stroke-width="10"/><path d="M72 128 C72 142 184 142 184 128" fill="none" stroke="#fff" stroke-width="8"/>',
    # lock (compliance/security)
    "lock": '<rect x="84" y="120" width="88" height="72" rx="12" fill="#fff"/><path d="M100 120 L100 96 C100 76 156 76 156 96 L156 120" fill="none" stroke="#fff" stroke-width="12"/><circle cx="128" cy="150" r="10" fill="{bg}"/>',
    # eye (intel/discovery)
    "eye": '<path d="M48 128 C80 84 176 84 208 128 C176 172 80 172 48 128 Z" fill="#fff"/><circle cx="128" cy="128" r="24" fill="{bg}"/><circle cx="128" cy="128" r="11" fill="#fff"/>',
    # bell (alerts/releases)
    "bell": '<path d="M128 56 C96 56 84 84 84 112 L84 148 L68 168 L188 168 L172 148 L172 112 C172 84 160 56 128 56 Z" fill="#fff"/><circle cx="128" cy="182" r="12" fill="#fff"/>',
    # funnel (filtering/deals)
    "funnel": '<path d="M60 72 L196 72 L148 136 L148 184 L108 200 L108 136 Z" fill="#fff"/>',
    # layers (stack/multi-source)
    "layers": '<path d="M128 52 L204 92 L128 132 L52 92 Z" fill="#fff"/><path d="M60 124 L128 158 L196 124" fill="none" stroke="#fff" stroke-width="11" stroke-linejoin="round"/><path d="M60 156 L128 190 L196 156" fill="none" stroke="#fff" stroke-width="11" stroke-linejoin="round"/>',
    # clock (scheduling/history)
    "clock": '<circle cx="128" cy="128" r="62" fill="#fff"/><line x1="128" y1="88" x2="128" y2="130" stroke="{bg}" stroke-width="11" stroke-linecap="round"/><line x1="128" y1="130" x2="158" y2="146" stroke="{bg}" stroke-width="11" stroke-linecap="round"/>',
    # pin (maps/local)
    "pin": '<path d="M128 52 C94 52 70 78 70 110 C70 152 128 204 128 204 C128 204 186 152 186 110 C186 78 162 52 128 52 Z" fill="#fff"/><circle cx="128" cy="108" r="22" fill="{bg}"/>',
}


def _pick_glyph(spec: Any) -> str:
    """Choose a glyph concept from the actor's name/events."""
    haystack = (spec.name + " " + " ".join(e.name for e in spec.pricing_events)).lower()
    rules = [
        ("screenshot", "camera"),
        ("vision", "camera"),
        ("serp", "search"),
        ("rank", "search"),
        ("search", "search"),
        ("crawl", "web"),
        ("harvest", "web"),
        ("backlink", "link"),
        ("link", "link"),
        ("monitor", "pulse"),
        ("watch", "pulse"),
        ("alert", "pulse"),
        ("change", "pulse"),
        ("price", "tag"),
        ("deal", "tag"),
        ("inventory", "tag"),
        ("tariff", "tag"),
        ("rate", "tag"),
        ("gdpr", "shield"),
        ("sanction", "shield"),
        ("safety", "scan"),
        ("rugpull", "scan"),
        ("token", "coin"),
        ("crypto", "coin"),
        ("listing", "coin"),
        ("sec", "scales"),
        ("court", "scales"),
        ("docket", "scales"),
        ("legal", "scales"),
        ("tender", "building"),
        ("procurement", "building"),
        ("directory", "building"),
        ("maps", "globe"),
        ("local", "globe"),
        ("property", "building"),
        ("flight", "plane"),
        ("hotel", "plane"),
        ("travel", "plane"),
        ("provider", "health"),
        ("health", "health"),
        ("clinical", "health"),
        ("trial", "health"),
        ("corpus", "document"),
        ("document", "document"),
        ("parser", "document"),
        ("markdown", "document"),
        ("newsletter", "rss"),
        ("podcast", "rss"),
        ("feed", "rss"),
        ("rss", "rss"),
        ("course", "edu"),
        ("scholarship", "edu"),
        ("grant", "edu"),
        ("weather", "chart"),
        ("air", "chart"),
        ("electricity", "chart"),
        ("economics", "chart"),
        ("cost", "chart"),
        ("onion", "web"),
        ("dark", "web"),
        ("lead", "search"),
        ("contact", "search"),
        ("form", "search"),
        ("tech", "scan"),
        ("stack", "scan"),
        ("blog", "document"),
        ("post", "document"),
        ("news", "document"),
        ("press", "document"),
        ("paper", "document"),
        ("event", "document"),
        ("job", "document"),
        ("review", "document"),
        ("accessibility", "scan"),
        ("social", "link"),
        ("card", "document"),
        ("meta", "document"),
        ("sitemap", "web"),
        ("diff", "pulse"),
        ("wayback", "document"),
        ("ssl", "shield"),
        ("cert", "shield"),
        ("broken", "scan"),
        ("universal", "search"),
        ("scraper", "search"),
        ("cve", "scan"),
        ("advisory", "bell"),
        ("release", "bell"),
        ("changelog", "bell"),
        ("terms", "shield"),
        ("policy", "shield"),
        ("forum", "chat"),
        ("discussion", "chat"),
        ("docs", "document"),
        ("status", "pulse"),
        ("uptime", "pulse"),
        ("stock", "tag"),
        ("menu", "document"),
        ("recipe", "document"),
        ("catalog", "layers"),
        ("aggregator", "layers"),
        ("multi", "layers"),
        ("history", "clock"),
        ("schedule", "clock"),
        ("interval", "clock"),
        ("local", "pin"),
        ("near", "pin"),
        ("collect", "database"),
        ("archive", "database"),
        ("dataset", "database"),
        ("discovery", "eye"),
        ("intel", "eye"),
        ("radar", "eye"),
        ("finder", "eye"),
        ("watcher", "eye"),
    ]
    for needle, glyph in rules:
        if needle in haystack and glyph in _GLYPHS:
            return glyph
    return "search"


def _category_for(spec: Any) -> str:
    name = spec.name.lower()
    for key, color in (
        ("crypto", "CRYPTO"),
        ("token", "CRYPTO"),
        ("serp", "SEO"),
        ("rank", "SEO"),
        ("seo", "SEO"),
        ("ad-intel", "SEO"),
        ("lead", "LEAD_GENERATION"),
        ("maps", "LEAD_GENERATION"),
        ("contact", "LEAD_GENERATION"),
        ("gdpr", "COMPLIANCE"),
        ("sanction", "COMPLIANCE"),
        ("sec-", "LEGAL"),
        ("court", "LEGAL"),
        ("docket", "LEGAL"),
        ("tender", "GOV"),
        ("hotel", "TRAVEL"),
        ("flight", "TRAVEL"),
        ("provider", "HEALTHCARE"),
        ("clinical", "HEALTHCARE"),
        ("trial", "HEALTHCARE"),
        ("price", "E_COMMERCE"),
        ("inventory", "E_COMMERCE"),
        ("deal", "E_COMMERCE"),
        ("review", "E_COMMERCE"),
        ("property", "E_COMMERCE"),
        ("llm", "AI"),
        ("corpus", "AI"),
        ("crawler", "CRAWLER"),
        ("monitor", "MONITOR"),
        ("watch", "MONITOR"),
    ):
        if key in name:
            return color
    return spec.category


def render_icon(spec: Any) -> str:
    """Render a deterministic store-quality SVG icon for the spec."""
    category = _category_for(spec)
    h1, h2 = CATEGORY_COLORS.get(category, CATEGORY_COLORS["SCRAPER"])
    glyph = _GLYPHS[_pick_glyph(spec)].replace("{bg}", f"hsl({h1},45%,38%)")
    seed = int(hashlib.md5(spec.name.encode(), usedforsecurity=False).hexdigest()[:4], 16)
    rotation = seed % 30 - 15  # subtle gradient angle variation

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        'width="256" height="256" role="img" aria-label="'
        + spec.title.replace("&", "&amp;").replace('"', "").replace("<", "&lt;")
        + '">\n'
        "<defs>\n"
        f'<linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%" '
        f'gradientTransform="rotate({rotation} 0.5 0.5)">\n'
        f'<stop offset="0%" stop-color="hsl({h1},74%,46%)"/>\n'
        f'<stop offset="55%" stop-color="hsl({h1},70%,38%)"/>\n'
        f'<stop offset="100%" stop-color="hsl({h2},72%,26%)"/>\n'
        "</linearGradient>\n"
        '<filter id="ds" x="-20%" y="-20%" width="140%" height="140%">\n'
        '<feDropShadow dx="0" dy="5" stdDeviation="7" '
        'flood-color="rgba(0,0,0,0.35)"/>\n'
        "</filter>\n"
        '<linearGradient id="gloss" x1="0%" y1="0%" x2="0%" y2="100%">\n'
        '<stop offset="0%" stop-color="rgba(255,255,255,0.22)"/>\n'
        '<stop offset="45%" stop-color="rgba(255,255,255,0.05)"/>\n'
        '<stop offset="100%" stop-color="rgba(255,255,255,0)"/>\n'
        "</linearGradient>\n</defs>\n"
        '<rect width="256" height="256" rx="52" fill="url(#bg)"/>\n'
        '<path d="M0 0 H256 V128 C170 158 86 158 0 128 Z" '
        'fill="url(#gloss)"/>\n'
        '<rect x="10" y="10" width="236" height="236" rx="44" '
        'fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="3"/>\n'
        f'<circle cx="212" cy="44" r="9" fill="hsl({h1},95%,72%)"/>\n'
        '<g opacity="0.08">\n'
        '<path d="M0 256 L256 210 L256 224 L0 256 Z" fill="#fff"/>\n'
        '<path d="M0 236 L256 190 L256 197 L0 245 Z" fill="#fff"/>\n'
        "</g>\n"
        f'<g filter="url(#ds)">{glyph}</g>\n'
        "</svg>\n"
    )
