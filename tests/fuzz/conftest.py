"""Fuzz test configuration.

Hypothesis PROFILES override per-test ``@settings`` decorators, so the profile
loaded here decides the deadline for every fuzz module regardless of what a
decorator says. Two consequences worth knowing:

* ``dev`` (deadline=500ms) was loaded UNCONDITIONALLY, including under CI. A
  single example that imports pypdf/lxml for the first time, or that runs on a
  worker sharing four cores with three other xdist workers, blows 500ms and
  Hypothesis reports ``FlakyFailure`` -- "failed on the first call but not on a
  subsequent one". MEASURED 2026-11-20: 14,069ms on the first run vs 0.15ms
  after, which is import cost, not a parser defect. These are NEVER-CRASH
  invariants, never latency assertions, so a deadline has no place in them.

* ``ci`` already exists with ``deadline=None`` and 1,000 examples. CI does not
  need to be told to use it -- detecting it here removes one more way for the
  two environments to disagree, which is how this flake existed in the first
  place.
"""

import os

from hypothesis import settings

settings.register_profile("ci", max_examples=1000, deadline=None)
settings.register_profile("dev", max_examples=100, deadline=500)

# CI markers: the runner sets CI=true; pytest-xdist sets the worker id; the
# explicit HYPOTHESIS_PROFILE override always wins.
_profile = os.getenv("HYPOTHESIS_PROFILE")
if not _profile:
    _profile = "ci" if os.getenv("CI") or os.getenv("PYTEST_XDIST_WORKER") else "dev"
settings.load_profile(_profile)
