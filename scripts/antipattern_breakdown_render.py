#!/usr/bin/env python3
"""Rendering for the antipattern triage report (counts come from the sibling).

Pure presentation: it formats the tally that ``antipattern_breakdown.scan``
produced and states whether the totals reconcile with the gate's own counts. It
holds no scanning logic, so it cannot disagree with the gate about what counts.
"""

from __future__ import annotations

from antipattern_breakdown import reconcile
from antipattern_handlers import EXPLICIT, PASSTHROUGH, SILENT, ZONES

# Column widths are >= the longest label in them, so headers never touch values.
_CLASS_WIDTHS = ((EXPLICIT, 25), (PASSTHROUGH, 20), (SILENT, 19))
_RULE_HEAD = (
    f"  {'rule':<16}{'tests/':>8}{'src/':>7}{'other':>7}{'total':>7}{'gate':>7}{'tests%':>8}"
)


def _rule_rows(data: dict, gate_counts: dict[str, int]) -> list[str]:
    """Aligned per-rule table: tests/ vs src/ vs other, worst rule first."""
    out = [_RULE_HEAD, "  " + "-" * (len(_RULE_HEAD) - 2)]
    order = sorted(data, key=lambda rule: -sum(z["n"] for z in data[rule].values()))
    for rule in order:
        zones = data[rule]
        total = sum(z["n"] for z in zones.values())
        if not total:
            continue
        share = f"{zones['tests']['n'] / total * 100:.0f}%"
        out.append(
            f"  {rule:<16}{zones['tests']['n']:>8}{zones['src']['n']:>7}"
            f"{zones['other']['n']:>7}{total:>7}{gate_counts.get(rule, 0):>7}{share:>8}"
        )
    return out


def _class_cells(bucket: dict) -> str:
    """Right-align the three handler classes in their fixed columns."""
    return "".join(f"{bucket[name]:>{width}}" for name, width in _CLASS_WIDTHS)


def _class_header() -> str:
    """The same columns, labelled by name rather than by width."""
    labels = "".join(f"{name:>{width}}" for name, width in _CLASS_WIDTHS)
    return "  " + f"{'zone':<8}{labels}{'total':>7}"


def _class_rows(data: dict) -> list[str]:
    """Explicit-failure vs passthrough vs silent, per zone then in total."""
    out = [_class_header()]
    for zone in ZONES:
        bucket = data["bare-except"][zone]
        if not bucket["n"]:
            continue
        out.append(f"  {zone:<8}{_class_cells(bucket)}{bucket['n']:>7}")
    grand = {name: sum(z[name] for z in data["bare-except"].values()) for name, _ in _CLASS_WIDTHS}
    out.append(f"  {'ALL':<8}{_class_cells(grand)}{sum(grand.values()):>7}")
    seen = sum(grand.values())
    if seen:
        share = "   ".join(f"{name} {grand[name] / seen * 100:.0f}%" for name, _ in _CLASS_WIDTHS)
        out.append(f"  {share}")
    return out


def render(data: dict, gate_counts: dict[str, int]) -> str:
    """Format the whole triage report, including the gate reconciliation."""
    drift = reconcile(data, gate_counts)
    out = [
        "breakdown (REPORTING ONLY — verdict, exit code and baseline unchanged)",
        "",
        *_rule_rows(data, gate_counts),
        "",
        "bare-except: explicit failure value vs silent fallthrough",
        *_class_rows(data),
        "",
        f"reconciles with gate counts: {'yes' if not drift else 'NO -> ' + ', '.join(drift)}",
        "zones are locations, not verdicts: a tests/ finding is idiomatic, not absent.",
    ]
    return "\n".join(out)
