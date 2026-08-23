# Pry Actor Standards

Every factory-generated actor MUST satisfy these requirements before it
can ship. They are enforced by `validate_generated()` + `lint_actor()` +
`lint_generated()` — CI fails on any violation. This is what "top-tier
operator" means in practice.

## Package completeness (automatic)

| Requirement | Enforced by |
|---|---|
| actor.json v1 spec (version `[N].[N]`, lowercase `dockerfile`) | spec validation |
| INPUT_SCHEMA.json byte-lockstep with embedded input | lockstep test |
| icon.svg (256×256 viewBox, category-colored, distinct per actor) | validate_generated |
| Dockerfile on apify/actor-python with pinned requirements.lock | lint |
| CHANGELOG.md (Console Information tab) | generator |
| dataset_schema.json (storages congruency) | generator |
| src/main.py wired to PPEScraperRunner | validate_generated |

## Input standards (winner patterns)

- **proxy_configuration** on every actor (Apify proxy passthrough)
- **max_items** visible cost cap, default 25 (cheap trials → good reviews)
- every field documented; required fields carry prefill or default
- prefills point at stable hosts only (daily-test survival)

## README standards (store best practices)

- ≥300 words (ours run ~600)
- Sections: What can this Actor do / Tutorial / How much will it cost /
  Input reference / Output reference / How can I use this data /
  More Pry actors / Apify API usage / FAQ / Support
- SEO keywords woven into the intro callout
- JSON output example present
- H2/H3 only (Store renders the name as H1)
- price-per-1,000-items stated explicitly

## Billing standards (PPE)

- primary event priced from economics.py arithmetic (≥40% margin at
  realistic load, enforced by test)
- synthetic events never charged manually
- error items pushed AND charged (work done = work billed)
- spending-limit stop + ABORTING flush handled by PPEScraperRunner

## Icon standards

- generated per preset: category gradient + concept glyph + deterministic
  variation; 52/52 currently distinct
- shipped as .actor/icon.svg, Console-upload ready

## Adding a new actor

1. Define the ActorSpec (name/title/description ≥80 chars, inputs,
   pricing event, processor if specialized).
2. Run the full gate: `pytest tests/test_actor_factory.py
   tests/test_actor_economics.py tests/test_actor_processors.py`.
3. Lint: zero findings required.
4. Generate, commit the package, push — CI publishes when APIFY_TOKEN
   is configured.
