"""Exception type for upstream payloads that do not match the promised shape.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations


class UpstreamPayloadError(ValueError):
    """An upstream returned a payload that does not match the expected shape.

    Separate from a plain ``ValueError`` so a fetch path can fail closed on a
    bad upstream answer while a genuine ``ValueError`` from our own code still
    surfaces instead of being read as "no data".
    """
