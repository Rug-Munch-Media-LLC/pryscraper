[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# ADR-0001: Initial Architecture

## Status
Accepted · 2026-07-02

## Context
First commit of PryScraper. Need to document the foundational choices.

## Decision
- **Language**: Python 3.12 + FastAPI
- **Port**: 8005
- **Deployment**: Docker container behind nginx
- **Source of truth**: forgejo
- **CI**: forgejo Actions
- **Secrets**: secrets manager

## Consequences
- All future decisions build on this foundation
- Breaking changes to these need a new ADR

## Alternatives
- _TBD_
