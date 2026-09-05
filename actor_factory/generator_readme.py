"""— Apify Actor Factory: README / store-copy rendering (facade).

Thin re-export facade over the split README-generation modules:

- ``generator_readme_render`` - full README assembly (``_render_readme``)
- ``generator_sections``     - FAQ / tutorial / limitations / troubleshooting / tips
- ``generator_examples``     - example dataset items and URL helpers
- ``generator_data_sources`` - data-source transparency sections
- ``generator_copy``         - SEO topic phrases, use cases, store description

Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from actor_factory.generator_copy import (
    _store_description,
    _topic,
    _use_case_bullets,
)
from actor_factory.generator_data_sources import (
    _DATA_SOURCES,
    _data_source_section,
)
from actor_factory.generator_examples import (
    _default_output_format,
    _example_item,
    _example_url,
)
from actor_factory.generator_readme_render import (
    _render_readme,
)
from actor_factory.generator_sections import (
    _limitations_section,
    _render_faq,
    _tips_section,
    _troubleshooting_section,
    _tutorial_steps,
)

__all__ = [
    "_DATA_SOURCES",
    "_data_source_section",
    "_default_output_format",
    "_example_item",
    "_example_url",
    "_limitations_section",
    "_render_faq",
    "_render_readme",
    "_store_description",
    "_tips_section",
    "_topic",
    "_troubleshooting_section",
    "_tutorial_steps",
    "_use_case_bullets",
]
