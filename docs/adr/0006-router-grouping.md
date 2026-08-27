# ADR 0006: Router Subpackage Grouping

**Status:** Accepted  
**Date:** 2026-08-26

## Context

84 routers lived in a single flat directory (`src/pry/api/routers/`). This was unwieldy and hard to navigate.

## Decision

Group routers into 7 domain subpackages:

```
src/pry/api/routers/
├── ai/           # AI-powered tools (agency, analysis, vision)
├── commerce/     # Payments, billing, marketplace
├── core/         # Auth, health, config, admin
├── data/         # Data domains (news, jobs, legal, etc.)
├── integrations/ # External integrations (email, webhooks, compliance)
├── scraping/     # Scraping engine endpoints
└── user/         # User management (CRM)
```

## Consequences

- **Positive:** Clear domain boundaries
- **Positive:** Easier to find and maintain related endpoints
- **Positive:** Scales better as new domains are added
- **Negative:** Import paths are longer
- **Negative:** Requires updating all imports (one-time cost)
