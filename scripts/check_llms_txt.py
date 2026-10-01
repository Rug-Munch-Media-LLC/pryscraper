"""``llms.txt`` must describe each MCP tool with that tool's own text.

``llms.txt`` is the file LLM clients read to choose a Pry tool, so a
section whose body was copy-pasted from another tool sends them to the
wrong endpoint. This module is imported by ``check-doc-claims.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REPO = Path(__file__).resolve().parent.parent


def check_llms_txt(
    problems: list[str], descs: dict[str, str], fail: Callable[[list[str], str], None]
) -> None:
    """Every llms.txt section must carry its own tool's description."""
    text = (REPO / "llms.txt").read_text()
    for sec in re.split(r"^### ", text, flags=re.M)[1:]:
        name = sec.split("\n", 1)[0].strip()
        if name not in descs:
            fail(problems, f"llms.txt: documents `{name}` which is not a PRY_TOOL")
        elif descs[name][:80] not in sec:
            fail(
                problems,
                f"llms.txt: `{name}` body does not match its real description "
                f"(copy-paste?) — regenerate from PRY_TOOLS",
            )
    missing = set(descs) - set(re.findall(r"^### (pry_\w+)$", text, re.M))
    if missing:
        fail(
            problems,
            f"llms.txt: {len(missing)} PRY_TOOL(s) have no section, e.g. {sorted(missing)[:3]}",
        )


def check_category_counts(
    problems: list[str],
    by_cat: dict[str, int],
    fail: Callable[[list[str], str], None],
) -> None:
    """llms.txt's per-category histogram must equal the real histogram."""
    text = (REPO / "llms.txt").read_text()
    claimed = {
        name: int(n) for name, n in re.findall(r"^\s*-\s*(\w+):\s*(\d+)\s+tools?\b", text, re.M)
    }
    for name, n in sorted(claimed.items()):
        if name not in by_cat:
            fail(problems, f"llms.txt: category `{name}` does not exist in PRY_TOOLS")
        elif by_cat[name] != n:
            fail(
                problems,
                f"llms.txt: category `{name}` claims {n} tools, real is {by_cat[name]}",
            )
    if claimed and sum(claimed.values()) != sum(by_cat.values()):
        fail(
            problems,
            f"llms.txt: category histogram sums to {sum(claimed.values())}, "
            f"PRY_TOOLS has {sum(by_cat.values())}",
        )
