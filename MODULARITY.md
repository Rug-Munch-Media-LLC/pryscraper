# Modularity rules

How a file becomes a module, and when a module splits. These are not
preferences: `scripts/check-structure.py` and `scripts/check-antipatterns.py`
enforce them, and both fail CI.

## The rules

1. **One module, one concern.** A module answers one question. If you cannot
   finish the sentence "this module is the place where …" without an "and",
   it is two modules.
2. **200 lines is the ceiling, 50 is the target.** A module over 200 fails
   unless allowlisted, and an allowlisted file may never grow.
3. **No monkeypatching.** Inject dependencies; do not reach into module
   state. `check-antipatterns.py` counts it and the count may only fall.
4. **Every failure path logs.** A `except` that swallows an error must emit a
   diagnostic or re-raise, otherwise it is a silent branch.
5. **Public API changes rarely.** When splitting, the import path stays
   identical — callers are not your migration project.

## How to split a module

1. List the top-level definitions. Concerns usually cluster: constants with
   their classifier, dataclasses with their models, parsers with their tree.
2. Name each cluster after the concern, not the technique
   (`roles.py`, not `heuristics.py`).
3. Move code **verbatim**. Refactoring and moving in one step hides which
   change broke it.
4. Put imports in the new modules, not in the caller. Then delete the old
   file so the gate sees the new ones.
5. Re-export the public names from the package `__init__.py`, including the
   old private ones if anything outside used them.
6. Run the tests **before** committing. A missing import does not show up
   until the test that exercises that path runs.

## Traps, from doing this twice

- **`from __future__ import annotations` is not enough for a type-only
  import.** Moving `_RawControl` under `if TYPE_CHECKING` satisfies TC001 and
  then trips F821, because the annotations still need the name at runtime
  for the resolver. Let ruff's `--unsafe-fixes` place both blocks.
- **Constants travel with their consumer.** `ROLE_*` belongs in the module
  that classifies roles, not the one that happens to read it.
- **`__all__` survives deletion.** Splitting a three-function module leaves
  the last copy naming functions that moved out. Re-export or trim it.
- **Check whether the gate will actually catch the thing.** A 500-line file
  is not in the allowlist and should hard-fail; verify rather than assume.
- **Do not split instance behaviour out of a class.** A method that reads
  `self._tier_*` is not a separate concern, it is what the object *is*.
  `scraper_orchestrate.py` has 38 `self._` references and its apparent
  helpers all take `self`; extracting them produced six `AttributeError`s.
  The real fix there is composing collaborators, not moving methods.
- **Count `self.` before you start.** If it is high, the split is a
  redesign, not a refactor, and belongs in its own change.
- **A never-raise wrapper turns a missing import into an empty result.**
  Splitting `sec_filings.py` left `filings.py` without the import it needed;
  the handler caught the NameError and returned `{}`, so tests failed with
  `KeyError` on a field rather than pointing at the import. After a split,
  assert on a *populated* result, not just that the call did not raise.
- **Follow the call graph, not the file order.** Splitting
  `sec_filings.py` failed twice on the same three tests because
  `_search_filings` resolves ticker to CIK through the cached ticker index
  *before* it calls the full-text search, so the cache has to stay with the
  module that reads it. Grep for every call a moved function makes, not
  only the ones inside its own block.
- **Tests that patch module internals must follow the code they patch.**
  That suite reached into `sec_filings._RETRY_CONFIG`; after the split the
  state moved, and the patch would have passed while neutering nothing.

## Worked example

`commerce/signup/form_detection.py` was 500 lines holding four concerns. It
is now a package, and the six call sites were untouched:

| module | lines | concern |
|---|---|---|
| `__init__.py` | 56 | public API, the only import path callers use |
| `fields.py` | 101 | assembling parsed controls into a form |
| `models.py` | 108 | `SignupField` / `SignupForm` |
| `roles.py` | 157 | classifying a control's role |
| `parser.py` | 174 | HTML to control tree |

`engine/` follows the same shape: `flaresolverr` is a transport, `altcha` a
captcha solver, `url_key` URL identity, and one module per search engine.

## Current state

245 source files exceed 200 lines: 201 are mechanically extractable and 44
need collaborator-based composition. The legal-docs, hosted-commerce API,
firmographics, sports-market, European-exchange, signup-verification,
US-books, billing-subscription, x402-pricing, capability-detection, x402-batch,
and healthcare-drug-pricing tranches are complete: those modules now live
behind stable package facades with explicit seams. Start the next tranche at
the top of `python3 scripts/modularity_queue.py --extract`; the largest
extractable file is the best demonstration and easiest to verify.
